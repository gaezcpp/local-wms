from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class MatToMat(models.Model):
    _name = 'mat.to.mat'
    _description = 'Material to Material'
    _rec_name = 'name'
    _order = 'id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    name = fields.Char(string="Name", default="New")
    date_done = fields.Date(string="Date Done")
    company_id = fields.Many2one(comodel_name='res.company', string="Company", default=lambda self:self.env.company)
    move_type = fields.Char(string="Move Type")
    select_all = fields.Boolean(string="Select All")
    is_checked = fields.Boolean(string="Is Checked")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('ready', 'Ready'),
        ('done', 'Done'),
        ('cancel', 'Cancel'),
    ], string="State", default='draft', tracking=True)
    warehouse_id = fields.Many2one(comodel_name='stock.warehouse', string="Warehouse")
    product_id = fields.Many2one(comodel_name='product.product', string="Source Product")
    location_id = fields.Many2one(comodel_name='stock.location', string="Source Location")
    product_dest_id = fields.Many2one(comodel_name='product.product', string="Destination Product")
    warehouse_dest_id = fields.Many2one(comodel_name='stock.warehouse', string="Destination WH")
    location_dest_id = fields.Many2one(comodel_name='stock.location', string="Destination Location")
    notes = fields.Text(string="Notes")
    picking_id = fields.Many2one(comodel_name='stock.picking', string="Generated Transfer")
    move_count = fields.Integer(string="Move Count", compute='_compute_related_counts')
    move_line_count = fields.Integer(string="Move Line Count", compute='_compute_related_counts')
    quant_count = fields.Integer(string="Quant Count", compute='_compute_related_counts')
    mat_source_ids = fields.One2many('mat.to.mat.source', 'mat_to_mat_id')
    mat_destination_ids = fields.One2many('mat.to.mat.destination', 'mat_to_mat_id')
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('mat.to.mat') or 'New'
            if not vals.get('move_type', ''):
                vals['move_type'] = self.env['ir.config_parameter'].sudo().get_param('mattomat_move_type_sap')
        return super().create(vals_list)
    
    @api.onchange('warehouse_id', 'product_id', 'lot_id', 'location_id')
    def _onchange_reset_checked(self):
        if self.is_checked:
            self.is_checked = False
    
    @api.onchange('select_all')
    def _onchange_select_all(self):
        for rec in self.mat_source_ids:
            if self.select_all:
                rec.is_selected = True
            else:
                rec.is_selected = False
                
    def action_check_availibility(self):
        quant_model = self.env['stock.quant'].sudo()
        source_mtm_model = self.env['mat.to.mat.source'].sudo()
        
        for rec in self:
            if rec.state != 'draft':
                continue
            
            rec.mat_source_ids.sudo().unlink()
        
            source_domain = [
                ('company_id', '=', rec.company_id.id),
                ('location_id.usage', '=', 'internal'),
            ]
            if rec.warehouse_id:
                source_domain.append(('warehouse_id', '=', rec.warehouse_id.id))
            if rec.product_id:
                source_domain.append(('product_id', '=', rec.product_id.id))
            if rec.location_id:
                source_domain.append(('location_id', 'child_of', rec.location_id.id))
            
            source_quant = quant_model.search(source_domain)
            if not source_quant:
                raise ValidationError("Data source product tidak ditemukan!")
            
            source_to_create = []
            for quant in source_quant:
                source_to_create.append({
                    'mat_to_mat_id': rec.id,
                    'quant_id': quant.id,
                    'product_id': quant.product_id.id or False,
                    'package_id': quant.package_id.id or False,
                    'location_id': quant.location_id.id,
                    'lot_id': quant.lot_id.id,
                    'quantity': quant.quantity,
                    'uom_id': quant.product_uom_id.id,
                    'pack_qty': quant.bag_qty,
                    'pack_uom_id': quant.uom_bag_id.id or False,
                })
            if source_to_create:
                source_mtm_model.create(source_to_create)
        
            rec.is_checked = True
                
    def action_mat_ready(self):
        for rec in self:
            if rec.state == 'draft' and rec.is_checked:
                if len(rec.mat_source_ids) <= 0 or not rec.mat_source_ids:
                    raise ValidationError("Silahkan lakukan Check Availability untuk pengisian Source")
                if not any(rec.mat_source_ids.mapped('is_selected')):
                    raise ValidationError("Minimal satu Source harus dipilih sebelum melanjutkan ke Ready!")
                not_selected = rec.mat_source_ids.filtered(lambda l: not l.is_selected)
                if not_selected:
                    not_selected.sudo().unlink()
                rec.write({'state': 'ready'})
            else:
                raise ValidationError("Hanya bisa ke Ready jika Status Draft dan sudah Check Availability")
    
    # ini yang pake stock.move
    def action_mat_done(self):
        sm = self.env['stock.move'].sudo()
        sml = self.env['stock.move.line'].sudo()
        picking_model = self.env['stock.picking'].sudo()
        
        virtual_loc = self.env.ref('stock.location_production', raise_if_not_found=False)
        if not virtual_loc:
            virtual_loc = self.env['stock.location'].search([('usage', '=', 'production'), ('company_id', '=', self.env.company.id)], limit=1)
        if not virtual_loc:
            raise ValidationError("Sistem membutuhkan lokasi tipe 'production' (Virtual Location) untuk memproses perubahan material.")

        for rec in self:
            if rec.state != 'ready':
                raise ValidationError("Hanya bisa Done dari status Ready!")
            
            selected_lines = rec.mat_source_ids.filtered(lambda l: l.is_selected)
            if not selected_lines:
                raise ValidationError("Tidak ada Source yang dipilih!")
                
            if not rec.product_dest_id:
                raise ValidationError("Destination Product belum ditentukan pada form!")
                
            if not rec.location_dest_id:
                raise ValidationError("Destination Location belum ditentukan pada form!")

            dest_vals = []
            moves_to_done = self.env['stock.move'].sudo()
            quants_to_update = [] # Menyimpan data untuk update stock.quant setelah move selesai
            
            is_diff_warehouse = rec.warehouse_id and rec.warehouse_dest_id and rec.warehouse_id != rec.warehouse_dest_id
            picking = False
            
            if is_diff_warehouse:
                picking_type = rec.warehouse_id.int_type_id
                if not picking_type:
                    picking_type = self.env['stock.picking.type'].search([
                        ('code', '=', 'internal'),
                        ('warehouse_id', '=', rec.warehouse_id.id),
                        ('company_id', '=', rec.company_id.id)
                    ], limit=1)
                
                if not picking_type:
                    raise ValidationError(f"Tidak ditemukan Operation Type 'Internal Transfer' untuk Warehouse {rec.warehouse_id.name}")

                picking = picking_model.create({
                    'picking_type_id': picking_type.id,
                    'location_id': rec.location_id.id or selected_lines[0].location_id.id,
                    'location_dest_id': rec.location_dest_id.id,
                    'origin': rec.name,
                    'company_id': rec.company_id.id,
                })

            for idx, line in enumerate(selected_lines, start=1):
                if line.quantity <= 0:
                    continue
                    
                # ==========================================
                # PERSIAPAN KUSTOM FIELD (MENGABAIKAN BOOLEAN & COMPUTE)
                # ==========================================
                sm_custom_vals = {}
                if 'sap_seq' in sm._fields:
                    sm_custom_vals['sap_seq'] = idx
                if 'order_seq' in sm._fields:
                    sm_custom_vals['order_seq'] = idx
                if 'order_selection' in sm._fields:
                    sm_custom_vals['order_selection'] = 'order'
                if 'product_packaging_id' in sm._fields and hasattr(line, 'quant_id') and hasattr(line.quant_id, 'product_packaging_id'):
                    pack_val = getattr(line.quant_id, 'product_packaging_id')
                    sm_custom_vals['product_packaging_id'] = pack_val.id if pack_val else False

                sml_custom_vals = {}
                if 'bag_qty' in sml._fields:
                    sml_custom_vals['bag_qty'] = line.pack_qty

                # Field yang disalin dari source quant ke SML
                sml_fields_to_copy = [
                    ('production_line_id', 'many2one'),
                    ('first_count', 'float'),
                    ('last_count', 'float'),
                    ('detail_text', 'char'),
                    ('sloc_id', 'many2one'),
                    ('stock_type', 'selection'),
                    ('qty_packaging_sap', 'float'),
                    ('pallet_status', 'selection'),
                    ('wh_category_id', 'many2one'),
                    ('suggest_dest_id', 'many2one'),
                    ('pallet_ke', 'integer'),
                    ('pallet_qty', 'float')
                ]
                
                if hasattr(line, 'quant_id') and line.quant_id:
                    for f_name, f_type in sml_fields_to_copy:
                        if f_name in sml._fields and hasattr(line.quant_id, f_name):
                            val = getattr(line.quant_id, f_name)
                            if f_type == 'many2one':
                                sml_custom_vals[f_name] = val.id if val else False
                            else:
                                sml_custom_vals[f_name] = val

                if 'stock_type' in sml._fields and not sml_custom_vals.get('stock_type'):
                    sml_custom_vals['stock_type'] = 'QI'
                    
                # ==========================================
                # 1. OUTWARD MOVE (Source -> Virtual)
                # ==========================================
                move_out_vals = {
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.quantity,
                    'product_uom': line.uom_id.id,
                    'location_id': line.location_id.id,
                    'location_dest_id': virtual_loc.id,
                    'company_id': rec.company_id.id,
                    'origin': rec.name,
                }
                move_out_vals.update(sm_custom_vals)
                move_out = sm.create(move_out_vals)
                
                move_out._action_confirm()
                move_out.move_line_ids.sudo().unlink() 
                
                sml_out_vals = {
                    'move_id': move_out.id,
                    'product_id': line.product_id.id,
                    'product_uom_id': line.uom_id.id,
                    'location_id': line.location_id.id,
                    'location_dest_id': virtual_loc.id,
                    'quantity': line.quantity,
                    'lot_id': line.lot_id.id if line.lot_id else False,
                    'package_id': line.package_id.id if line.package_id else False,
                }
                sml_out_vals.update(sml_custom_vals)
                sml.create(sml_out_vals)
                move_out.picked = True 
                
                # ==========================================
                # 2. PENANGANAN LOT
                # ==========================================
                dest_lot_id = False
                if rec.product_dest_id.tracking in ['lot', 'serial']:
                    new_lot_name = line.lot_id.name if line.lot_id else rec.name
                    dest_lot = self.env['stock.lot'].sudo().search([
                        ('name', '=', new_lot_name),
                        ('product_id', '=', rec.product_dest_id.id),
                        ('company_id', '=', rec.company_id.id)
                    ], limit=1)
                    
                    if not dest_lot:
                        dest_lot = self.env['stock.lot'].sudo().create({
                            'name': new_lot_name,
                            'product_id': rec.product_dest_id.id,
                            'company_id': rec.company_id.id,
                        })
                    dest_lot_id = dest_lot.id
                
                # ==========================================
                # 3. INWARD MOVE (Virtual -> Destination)
                # ==========================================
                final_in_loc = rec.location_id.id if is_diff_warehouse else rec.location_dest_id.id
                
                move_in_vals = {
                    'product_id': rec.product_dest_id.id,
                    'product_uom_qty': line.quantity,
                    'product_uom': rec.product_dest_id.uom_id.id,
                    'location_id': virtual_loc.id,
                    'location_dest_id': final_in_loc,
                    'company_id': rec.company_id.id,
                    'origin': rec.name,
                }
                move_in_vals.update(sm_custom_vals)
                move_in = sm.create(move_in_vals)
                
                move_in._action_confirm()
                move_in.move_line_ids.sudo().unlink() 
                
                sml_in_vals = {
                    'move_id': move_in.id,
                    'product_id': rec.product_dest_id.id,
                    'product_uom_id': rec.product_dest_id.uom_id.id,
                    'location_id': virtual_loc.id,
                    'location_dest_id': final_in_loc,
                    'quantity': line.quantity,
                    'lot_id': dest_lot_id,
                    'package_id': line.package_id.id if line.package_id else False,
                }
                sml_in_vals.update(sml_custom_vals)
                sml.create(sml_in_vals)
                move_in.picked = True 
                
                moves_to_done |= (move_out | move_in)

                # Simpan metadata untuk update stock.quant setelah di-done
                if hasattr(line, 'quant_id') and line.quant_id:
                    quants_to_update.append({
                        'src_quant': line.quant_id,
                        'product_id': rec.product_dest_id.id,
                        'location_id': final_in_loc,
                        'lot_id': dest_lot_id,
                        'package_id': line.package_id.id if line.package_id else False,
                    })

                # ==========================================
                # 4. TRANSFER INTERNAL JIKA BEDA WAREHOUSE
                # ==========================================
                if is_diff_warehouse and picking:
                    sm_transfer_vals = {
                        'picking_id': picking.id,
                        'product_id': rec.product_dest_id.id,
                        'product_uom_qty': line.quantity,
                        'product_uom': rec.product_dest_id.uom_id.id,
                        'location_id': final_in_loc,
                        'location_dest_id': rec.location_dest_id.id,
                        'company_id': rec.company_id.id,
                        'origin': rec.name,
                    }
                    sm_transfer_vals.update(sm_custom_vals)
                    sm.create(sm_transfer_vals)

                # ==========================================
                # 5. REKAM DESTINATION TAB
                # ==========================================
                dest_vals.append((0, 0, {
                    'quant_id': False,
                    'product_id': rec.product_dest_id.id,
                    'location_id': rec.location_dest_id.id,
                    'quantity': line.quantity,
                    'uom_id': rec.product_dest_id.uom_id.id,
                    'pack_qty': line.pack_qty,
                    'pack_uom_id': line.pack_uom_id.id if line.pack_uom_id else False,
                    'package_id': line.package_id.id if line.package_id else False,
                    'lot_id': dest_lot_id,
                }))

            # ==========================================
            # EKSEKUSI DONE & POST-PROCESSING QUANT
            # ==========================================
            if moves_to_done:
                moves_to_done._action_done()

            # Copas field kustom khusus stock.quant yang tidak ada di stock.move.line
            quant_model = self.env['stock.quant'].sudo()
            for q_data in quants_to_update:
                src_q = q_data['src_quant']
                dest_q = quant_model.search([
                    ('product_id', '=', q_data['product_id']),
                    ('location_id', '=', q_data['location_id']),
                    ('lot_id', '=', q_data['lot_id']),
                    ('package_id', '=', q_data['package_id'])
                ], limit=1)

                if dest_q:
                    q_update_vals = {}
                    fields_to_sync = [
                        'exp_group', 'inbound_date', 'stock_type', 'production_line_id', 
                        'bag_qty', 'pallet_qty', 'bag_dummy_qty', 'pallet_ke'
                    ]
                    for f in fields_to_sync:
                        if hasattr(dest_q, f) and hasattr(src_q, f):
                            val = getattr(src_q, f)
                            # Handle relasional Many2one agar diambil ID-nya saja
                            if dest_q._fields[f].type == 'many2one':
                                q_update_vals[f] = val.id if val else False
                            else:
                                q_update_vals[f] = val

                    if q_update_vals:
                        dest_q.write(q_update_vals)

            if picking:
                picking.action_confirm()
                picking.action_assign()

            rec.write({
                'mat_destination_ids': dest_vals,
                'picking_id': picking.id if picking else False,
                'state': 'done',
                'date_done': fields.Date.today()
            })
    
    # ini yang langsung dari stock.quant
    # def action_mat_done(self):
    #     quant_obj = self.env['stock.quant'].sudo()
    #     lot_obj = self.env['stock.lot'].sudo()
        
    #     for rec in self:
    #         if rec.state != 'ready':
    #             raise ValidationError("Hanya bisa Done dari status Ready!")
            
    #         selected_lines = rec.mat_source_ids.filtered(lambda l: l.is_selected)
    #         if not selected_lines:
    #             raise ValidationError("Tidak ada Source yang dipilih!")
                
    #         if not rec.product_dest_id:
    #             raise ValidationError("Destination Product belum ditentukan pada form!")

    #         dest_vals = []

    #         for line in selected_lines:
    #             if line.quantity <= 0:
    #                 continue
                    
    #             # 1. Kurangi stok Source
    #             # Jika stok asal 200 dan dikurangi 200, otomatis jadi 0
    #             quant_obj._update_available_quantity(
    #                 product_id=line.product_id, 
    #                 location_id=line.location_id, 
    #                 quantity=-line.quantity, 
    #                 lot_id=line.lot_id, 
    #                 package_id=line.package_id
    #             )
                
    #             # 2. Tangani Lot untuk Destination Product
    #             # Karena Lot terikat pada product_id, kita harus cari atau buat Lot baru
    #             # dengan nama yang sama untuk product_dest_id
    #             dest_lot_id = False
    #             if line.lot_id:
    #                 dest_lot = lot_obj.search([
    #                     ('name', '=', line.lot_id.name),
    #                     ('product_id', '=', rec.product_dest_id.id),
    #                     ('company_id', '=', rec.company_id.id)
    #                 ], limit=1)
                    
    #                 if not dest_lot:
    #                     # Buat lot baru jika belum ada
    #                     dest_lot = lot_obj.create({
    #                         'name': line.lot_id.name,
    #                         'product_id': rec.product_dest_id.id,
    #                         'company_id': rec.company_id.id,
    #                     })
                        
    #                     # Salin semua record lot_aft_ids dari source ke destination
    #                     for aft in line.lot_id.lot_aft_ids:
    #                         aft.copy({'lot_id': dest_lot.id})
                            
    #                 dest_lot_id = dest_lot
                
    #             # 3. Tambah stok Destination
    #             # Odoo otomatis membuat stock.quant baru dengan package_id dan lot_id yang sesuai
    #             quant_obj._update_available_quantity(
    #                 product_id=rec.product_dest_id, 
    #                 location_id=line.location_id, 
    #                 quantity=line.quantity,
    #                 lot_id=dest_lot_id,
    #                 package_id=line.package_id
    #             )

    #             # Cari record quant yang baru saja diupdate/dibuat
    #             dest_quant = quant_obj.search([
    #                 ('product_id', '=', rec.product_dest_id.id),
    #                 ('location_id', '=', line.location_id.id),
    #                 ('lot_id', '=', dest_lot_id.id if dest_lot_id else False),
    #                 ('package_id', '=', line.package_id.id if line.package_id else False)
    #             ], limit=1)

    #             # Masukkan ke dalam tab Destination beserta quant_id, package_id, dan lot_id
    #             dest_vals.append((0, 0, {
    #                 'quant_id': dest_quant.id if dest_quant else False,
    #                 'package_id': line.package_id.id if line.package_id else False,
    #                 'lot_id': dest_lot_id.id if dest_lot_id else False,
    #                 'product_id': rec.product_dest_id.id,
    #                 'location_id': line.location_id.id,
    #                 'quantity': line.quantity,
    #                 'uom_id': rec.product_dest_id.uom_id.id,
    #                 'pack_qty': line.pack_qty,
    #                 'pack_uom_id': line.pack_uom_id.id if line.pack_uom_id else False,
    #             }))

    #         # Update status dokumen dan isi tab destination
    #         rec.write({
    #             'mat_destination_ids': dest_vals,
    #             'state': 'done',
    #             'date_done': fields.Date.today()
    #         })
        
    def action_mat_cancel(self):
        for rec in self:
            if rec.state != 'ready':
                raise ValidationError("Cancel hanya bisa dilakukan pada status Ready")
            rec.mat_source_ids.sudo().unlink()
            rec.mat_destination_ids.sudo().unlink()
            rec.write({'state': 'cancel'})
            rec.message_post(body=f"{rec.name} Tab Source dan Destination dikosongkan karena proses cancel!")

    def _compute_related_counts(self):
        # 1. Inisialisasi nilai awal
        for rec in self:
            rec.move_count = 0
            rec.move_line_count = 0
            rec.quant_count = 0

        # Kumpulkan semua nama dokumen (origin) untuk filter query secara batch
        doc_names = self.mapped('name')
        if not doc_names:
            return

        # 2. Hitung Stock Move dengan read_group
        move_groups = self.env['stock.move'].sudo().read_group(
            domain=[('origin', 'in', doc_names)],
            fields=['origin'],
            groupby=['origin']
        )
        move_count_data = {group['origin']: group['origin_count'] for group in move_groups}

        # Karena stock.move.line tidak memiliki field 'origin', 
        # kita butuh pemetaan dari dokumen -> move -> move_line
        moves = self.env['stock.move'].sudo().search([('origin', 'in', doc_names)])
        
        move_to_origin = {move.id: move.origin for move in moves}
        sml_count_data = {}

        if moves:
            # 3. Hitung Stock Move Line dengan read_group
            sml_groups = self.env['stock.move.line'].sudo().read_group(
                domain=[('move_id', 'in', moves.ids)],
                fields=['move_id'],
                groupby=['move_id']
            )
            # Agregasi data SML kembali ke nama dokumen asal
            for group in sml_groups:
                move_id = group['move_id'][0]
                origin = move_to_origin.get(move_id)
                if origin:
                    sml_count_data[origin] = sml_count_data.get(origin, 0) + group['move_id_count']

        # 4. Assign hasil mapping ke masing-masing record
        for rec in self:
            rec.move_count = move_count_data.get(rec.name, 0)
            rec.move_line_count = sml_count_data.get(rec.name, 0)
            
            # Catatan untuk Quant:
            # stock.quant tidak memiliki referensi 'origin' atau 'move_id'. 
            # Pencarian quant didasarkan pada stok aktual di lokasi hasil transaksi.
            # Menggunakan search_count lebih ringkas untuk kasus ini jika datanya tidak masif per baris.
            dest_products = rec.mat_destination_ids.mapped('product_id').ids
            if dest_products and rec.location_dest_id:
                rec.quant_count = self.env['stock.quant'].sudo().search_count([
                    ('product_id', 'in', dest_products),
                    ('location_id', 'child_of', rec.location_dest_id.id)
                ])

    def action_view_stock_moves(self):
        self.ensure_one()
        moves = self.env['stock.move'].sudo().search([('origin', '=', self.name)])
        return {
            'name': 'Stock Moves',
            'type': 'ir.actions.act_window',
            'res_model': 'stock.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', moves.ids)],
        }

    def action_view_stock_move_lines(self):
        self.ensure_one()
        moves = self.env['stock.move'].sudo().search([('origin', '=', self.name)])
        move_lines = self.env['stock.move.line'].sudo().search([('move_id', 'in', moves.ids)])
        return {
            'name': 'Stock Move Lines',
            'type': 'ir.actions.act_window',
            'res_model': 'stock.move.line',
            'view_mode': 'list,form',
            'domain': [('id', 'in', move_lines.ids)],
        }

    def action_view_stock_quants(self):
        self.ensure_one()
        dest_products = self.mat_destination_ids.mapped('product_id').ids
        dest_locations = [self.location_dest_id.id] if self.location_dest_id else []
        quants = self.env['stock.quant'].sudo().search([
            ('product_id', 'in', dest_products),
            ('location_id', 'child_of', dest_locations)
        ])
        return {
            'name': 'Stock Quants',
            'type': 'ir.actions.act_window',
            'res_model': 'stock.quant',
            'view_mode': 'list,form',
            'domain': [('id', 'in', quants.ids)],
        }
    
class MatToMatSource(models.Model):
    _name = 'mat.to.mat.source'
    _description = 'Mat to Mat Source'
    
    mat_to_mat_id = fields.Many2one(comodel_name='mat.to.mat')
    quant_id = fields.Many2one(comodel_name='stock.quant')
    location_id = fields.Many2one(comodel_name='stock.location', string="Location")
    product_id = fields.Many2one(comodel_name='product.product', string="Product")
    package_id = fields.Many2one(comodel_name='stock.package', string="Package")
    lot_id = fields.Many2one(comodel_name='stock.lot', string="Lot")
    quantity = fields.Float(string="Quantity")
    uom_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    pack_qty = fields.Float(string="Pack Qty")
    pack_uom_id = fields.Many2one(comodel_name='uom.uom', string="Units")
    stock_type = fields.Selection([
        ('QI', 'QI'),
        ('BLOCKED', 'BLOCKED'),
        ('UU', 'UU'),
    ], string="Stock Type")
    is_selected = fields.Boolean(string="Select")
    
    
class MatToMatDestination(models.Model):
    _name = 'mat.to.mat.destination'
    _description = 'Mat to Mat Destination'
    
    mat_to_mat_id = fields.Many2one(comodel_name='mat.to.mat')
    quant_id = fields.Many2one(comodel_name='stock.quant')
    location_id = fields.Many2one(comodel_name='stock.location', string="Location")
    product_id = fields.Many2one(comodel_name='product.product', string="Product")
    package_id = fields.Many2one(comodel_name='stock.package', string="Package")
    lot_id = fields.Many2one(comodel_name='stock.lot', string="Lot")
    quantity = fields.Float(string="Quantity")
    uom_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    pack_qty = fields.Float(string="Pack Qty")
    pack_uom_id = fields.Many2one(comodel_name='uom.uom', string="Units")
    stock_type = fields.Selection([
        ('QI', 'QI'),
        ('BLOCKED', 'BLOCKED'),
        ('UU', 'UU'),
    ], string="Stock Type")