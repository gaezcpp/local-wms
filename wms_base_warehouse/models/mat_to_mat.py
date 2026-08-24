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

    _QUANT_FIELDS_TO_SYNC = [
        'exp_group', 'inbound_date', 'stock_type', 'production_line_id',
        'bag_qty', 'pallet_qty', 'bag_dummy_qty', 'pallet_ke',
    ]

    _LOT_FIELDS_TO_INHERIT = [
        'ref', 'note',
        'expiration_date', 'use_date', 'removal_date', 'alert_date',
        'production_line_id', 'po_sap_id',
    ]

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
                    'stock_type': quant.stock_type,
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
                if rec.warehouse_id and rec.warehouse_dest_id:
                    if rec.warehouse_id != rec.warehouse_dest_id and not rec.location_dest_id:
                        raise ValidationError("Destination Location harus diisi apabila warehouse berbeda!")
                not_selected = rec.mat_source_ids.filtered(lambda l: not l.is_selected)
                if not_selected:
                    not_selected.sudo().unlink()
                rec.write({'state': 'ready'})
            else:
                raise ValidationError("Hanya bisa ke Ready jika Status Draft dan sudah Check Availability")
    
    def _check_source_still_available(self, selected_lines):
        self.ensure_one()
        quant_model = self.env['stock.quant'].sudo()
        shortages = []

        for line in selected_lines:
            if line.quantity <= 0:
                continue

            quants = quant_model._gather(
                line.product_id,
                line.location_id,
                lot_id=line.lot_id,
                package_id=line.package_id,
                strict=True,
            )
            on_hand = sum(quants.mapped('quantity'))
            if line.uom_id.compare(line.quantity, on_hand) > 0:
                shortages.append(
                    f"- {line.product_id.display_name} "
                    f"[{line.package_id.name or '-'} / {line.lot_id.name or '-'}] "
                    f"di {line.location_id.display_name}: "
                    f"diminta {line.quantity}, tersedia {on_hand}"
                )

            reserved = sum(quants.mapped('reserved_quantity'))
            if reserved:
                _logger.warning(
                    "%s: quant sumber %s (package %s, lot %s) punya reserved_quantity %s, "
                    "reservasi dokumen lain akan dilepas oleh proses Mat to Mat ini.",
                    self.name, line.product_id.display_name,
                    line.package_id.name or '-', line.lot_id.name or '-', reserved,
                )

        if shortages:
            raise ValidationError(
                "Stok sumber sudah berubah sejak Check Availability, proses dibatalkan "
                "agar tidak membuat stok minus:\n\n"
                + "\n".join(shortages)
                + "\n\nSilahkan kembalikan ke Draft dan lakukan Check Availability ulang."
            )

    def _get_virtual_adjustment_location(self):
        self.ensure_one()
        company = self.company_id or self.env.company

        # location = self.product_dest_id.with_company(company).property_stock_inventory
        location = self.env['stock.location'].search([
            ('usage', '=', 'inventory'),
            ('company_id', '=', company.id),
            ('barcode', '=', 'ADJUSTMENT'),
        ], limit=1)
        # if not location:
        if not location:
            raise ValidationError(
                "Sistem membutuhkan lokasi virtual Inventory Adjustment pada company "
                f"{company.display_name} untuk memproses perubahan material."
            )
        return location

    def _prepare_dest_lot_inherited_vals(self, src_lot):
        self.ensure_one()
        if not src_lot:
            return {}

        lot_model = self.env['stock.lot']
        vals = {}
        for f_name in self._LOT_FIELDS_TO_INHERIT:
            if f_name not in lot_model._fields or f_name not in src_lot._fields:
                continue
            val = src_lot[f_name]
            if not val:
                continue
            vals[f_name] = val.id if lot_model._fields[f_name].type == 'many2one' else val
        return vals

    def _compute_bag_qty(self, line):
        uom_bag = line.product_id.uom_bag_id if 'uom_bag_id' in line.product_id._fields else False
        if not uom_bag or not line.uom_id:
            return 0.0
        return line.uom_id._compute_quantity(line.quantity, uom_bag)

    def _transfer_lot_aft(self, aft_transfers):
        self.ensure_one()
        if not aft_transfers:
            return

        if self.company_id in self.env['stock.quant'].sudo()._get_upload_stock_companies():
            _logger.info(
                "%s: transfer lot.aft dilewati, company %s memakai recompute _sync_to_lot_aft.",
                self.name, self.company_id.display_name,
            )
            return

        aft_model = self.env['stock.lot.aft'].sudo()
        for (src_lot_id, dest_lot_id, stock_type), data in aft_transfers.items():
            src_aft = aft_model.search([
                ('lot_id', '=', src_lot_id),
                ('stock_type', '=', stock_type),
            ], limit=1)

            if not src_aft:
                _logger.warning(
                    "%s: stock.lot.aft sumber tidak ditemukan (lot %s, stock_type %s), "
                    "saldo tidak dipindah.",
                    self.name, src_lot_id, stock_type,
                )
                continue

            take_qty = min(src_aft.quantity, data['quantity'])
            take_bag = min(src_aft.bag_qty, data['bag_qty'])
            if take_qty < data['quantity'] or take_bag < data['bag_qty']:
                _logger.warning(
                    "%s: saldo stock.lot.aft lot %s (%s) kurang dari qty yang dikonversi "
                    "(minta %s/%s bag, tersedia %s/%s bag). Yang dipindah hanya sebesar saldo.",
                    self.name, src_lot_id, stock_type,
                    data['quantity'], data['bag_qty'], src_aft.quantity, src_aft.bag_qty,
                )

            if take_qty <= 0 and take_bag <= 0:
                continue

            src_aft.write({
                'quantity': src_aft.quantity - take_qty,
                'bag_qty': src_aft.bag_qty - take_bag,
            })

            dest_aft = aft_model.search([
                ('lot_id', '=', dest_lot_id),
                ('stock_type', '=', stock_type),
            ], limit=1)
            if dest_aft:
                dest_aft.write({
                    'quantity': dest_aft.quantity + take_qty,
                    'bag_qty': dest_aft.bag_qty + take_bag,
                })
            else:
                aft_model.create({
                    'lot_id': dest_lot_id,
                    'stock_type': stock_type,
                    'quantity': take_qty,
                    'bag_qty': take_bag,
                    'uom_id': self.product_dest_id.uom_id.id,
                    'uom_bag_id': (
                        self.product_dest_id.uom_bag_id.id
                        if 'uom_bag_id' in self.product_dest_id._fields and self.product_dest_id.uom_bag_id
                        else src_aft.uom_bag_id.id
                    ),
                })

    # ini yang pake stock.move
    def action_mat_done(self):
        sm = self.env['stock.move'].sudo()
        sml = self.env['stock.move.line'].sudo()
        quant_model = self.env['stock.quant'].sudo()
        lot_model = self.env['stock.lot'].sudo()
        picking_model = self.env['stock.picking'].sudo()

        for rec in self:
            if rec.state != 'ready':
                raise ValidationError("Hanya bisa Done dari status Ready!")

            selected_lines = rec.mat_source_ids.filtered(lambda l: l.is_selected)
            if not selected_lines:
                raise ValidationError("Tidak ada Source yang dipilih!")
                
            if not rec.product_dest_id:
                raise ValidationError("Destination Product belum ditentukan pada form!")

            if not rec.location_dest_id and rec.warehouse_dest_id and rec.warehouse_id != rec.warehouse_dest_id:
                raise ValidationError(
                    "Destination Location wajib diisi kalau Destination WH berbeda dengan Warehouse asal!"
                )

            rec._check_source_still_available(selected_lines)

            virtual_loc = rec._get_virtual_adjustment_location()

            moves_out_todo = self.env['stock.move'].sudo()
            moves_in_todo = self.env['stock.move'].sudo()
            quants_to_update = [] 
            aft_transfers = {}

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
                    'result_package_id': False,
                }
                sml_out_vals.update(sml_custom_vals)
                sml.create(sml_out_vals)
                move_out.picked = True 
                
                dest_lot_id = False
                if rec.product_dest_id.tracking in ['lot', 'serial']:
                    new_lot_name = line.lot_id.name if line.lot_id else rec.name
                    dest_lot = lot_model.search([
                        ('name', '=', new_lot_name),
                        ('product_id', '=', rec.product_dest_id.id),
                        ('company_id', '=', rec.company_id.id)
                    ], limit=1)

                    if not dest_lot:
                        lot_vals = {
                            'name': new_lot_name,
                            'product_id': rec.product_dest_id.id,
                            'company_id': rec.company_id.id,
                        }
                        lot_vals.update(rec._prepare_dest_lot_inherited_vals(line.lot_id))
                        dest_lot = lot_model.create(lot_vals)
                    dest_lot_id = dest_lot.id

                    if line.lot_id:
                        aft_key = (line.lot_id.id, dest_lot_id, sml_custom_vals.get('stock_type'))
                        aft_data = aft_transfers.setdefault(aft_key, {'quantity': 0.0, 'bag_qty': 0.0})
                        aft_data['quantity'] += line.quantity
                        aft_data['bag_qty'] += line.pack_qty or rec._compute_bag_qty(line)

                if is_diff_warehouse:
                    final_in_loc = line.location_id.id
                else:
                    final_in_loc = rec.location_dest_id.id or line.location_id.id

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
                    'package_id': False,
                    'result_package_id': line.package_id.id if line.package_id else False,
                }
                sml_in_vals.update(sml_custom_vals)
                sml.create(sml_in_vals)
                move_in.picked = True

                moves_out_todo |= move_out
                moves_in_todo |= move_in

                src_quant_vals = {}
                if line.quant_id:
                    for f in self._QUANT_FIELDS_TO_SYNC:
                        if f not in quant_model._fields:
                            continue
                        val = line.quant_id[f]
                        src_quant_vals[f] = (
                            (val.id if val else False)
                            if quant_model._fields[f].type == 'many2one'
                            else val
                        )

                quants_to_update.append({
                    'src_quant_vals': src_quant_vals,
                    'product_id': rec.product_dest_id.id,
                    'location_id': final_in_loc,
                    'display_location_id': rec.location_dest_id.id or final_in_loc,
                    'lot_id': dest_lot_id,
                    'package_id': line.package_id.id if line.package_id else False,
                    'quantity': line.quantity,
                    'pack_qty': line.pack_qty,
                    'pack_uom_id': line.pack_uom_id.id if line.pack_uom_id else False,
                    'stock_type': sml_custom_vals.get('stock_type'),
                })

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

            if moves_out_todo:
                moves_out_todo._action_done()
            if moves_in_todo:
                moves_in_todo._action_done()

            dest_vals = []
            for q_data in quants_to_update:
                dest_q = quant_model.search([
                    ('product_id', '=', q_data['product_id']),
                    ('location_id', '=', q_data['location_id']),
                    ('lot_id', '=', q_data['lot_id']),
                    ('package_id', '=', q_data['package_id']),
                    ('company_id', '=', rec.company_id.id),
                ], limit=1)

                if not dest_q:
                    _logger.warning(
                        "%s: quant tujuan tidak ditemukan (product %s, location %s, lot %s, package %s)",
                        rec.name, q_data['product_id'], q_data['location_id'],
                        q_data['lot_id'], q_data['package_id'],
                    )
                elif q_data['src_quant_vals']:
                    dest_q.write(q_data['src_quant_vals'])

                dest_vals.append((0, 0, {
                    'quant_id': dest_q.id if dest_q else False,
                    'product_id': q_data['product_id'],
                    'location_id': q_data['display_location_id'],
                    'quantity': q_data['quantity'],
                    'uom_id': rec.product_dest_id.uom_id.id,
                    'pack_qty': q_data['pack_qty'],
                    'pack_uom_id': q_data['pack_uom_id'],
                    'package_id': q_data['package_id'],
                    'lot_id': q_data['lot_id'],
                    'stock_type': q_data['stock_type'],
                }))

            rec._transfer_lot_aft(aft_transfers)

            if picking:
                picking.action_confirm()
                picking.action_assign()
                keep_pallet = picking.move_line_ids.filtered(
                    lambda ml: ml.package_id and not ml.result_package_id
                )
                for ml in keep_pallet:
                    ml.write({'result_package_id': ml.package_id.id})

            rec.write({
                'mat_destination_ids': dest_vals,
                'picking_id': picking.id if picking else False,
                'state': 'done',
                'date_done': fields.Date.today()
            })

    def action_mat_cancel(self):
        for rec in self:
            if rec.state != 'ready':
                raise ValidationError("Cancel hanya bisa dilakukan pada status Ready")
            rec.mat_source_ids.sudo().unlink()
            rec.mat_destination_ids.sudo().unlink()
            rec.write({'state': 'cancel'})
            rec.message_post(body=f"{rec.name} Tab Source dan Destination dikosongkan karena proses cancel!")

    def _compute_related_counts(self):
        for rec in self:
            rec.move_count = 0
            rec.move_line_count = 0
            rec.quant_count = 0

        doc_names = [name for name in self.mapped('name') if name]
        if not doc_names:
            return

        moves = self.env['stock.move'].sudo().search_fetch([('origin', 'in', doc_names)], ['origin'])
        move_to_origin = {move.id: move.origin for move in moves}

        move_count_data = {}
        for origin in move_to_origin.values():
            move_count_data[origin] = move_count_data.get(origin, 0) + 1

        sml_count_data = {}
        if moves:
            sml_groups = self.env['stock.move.line'].sudo()._read_group(
                [('move_id', 'in', moves.ids)],
                groupby=['move_id'],
                aggregates=['__count'],
            )
            for move, count in sml_groups:
                origin = move_to_origin.get(move.id)
                if origin:
                    sml_count_data[origin] = sml_count_data.get(origin, 0) + count

        for rec in self:
            rec.move_count = move_count_data.get(rec.name, 0)
            rec.move_line_count = sml_count_data.get(rec.name, 0)
            dest_products = rec.mat_destination_ids.mapped('product_id').ids
            dest_locations = (
                rec.location_dest_id
                or rec.mat_destination_ids.mapped('location_id')
            ).ids
            if dest_products and dest_locations:
                rec.quant_count = self.env['stock.quant'].sudo().search_count([
                    ('product_id', 'in', dest_products),
                    ('location_id', 'child_of', dest_locations)
                ])

    def action_view_stock_moves(self):
        self.ensure_one()
        moves = self.env['stock.move'].sudo().search([('origin', '=', self.name)])
        return {
            'name': 'Stock Moves',
            'type': 'ir.actions.act_window',
            'res_model': 'stock.move',
            'view_mode': 'list',
            'domain': [('id', 'in', moves.ids)],
            'context': {
                'create': 0,
                'edit': 0,
                'delete': 0,
                'duplicate': 0,
            }
        }

    def action_view_stock_move_lines(self):
        self.ensure_one()
        moves = self.env['stock.move'].sudo().search([('origin', '=', self.name)])
        move_lines = self.env['stock.move.line'].sudo().search([('move_id', 'in', moves.ids)])
        return {
            'name': 'Stock Move Lines',
            'type': 'ir.actions.act_window',
            'res_model': 'stock.move.line',
            'view_mode': 'list',
            'domain': [('id', 'in', move_lines.ids)],
            'context': {
                'create': 0,
                'edit': 0,
                'delete': 0,
                'duplicate': 0,
            }
        }

    def action_view_stock_quants(self):
        self.ensure_one()
        dest_products = self.mat_destination_ids.mapped('product_id').ids
        dest_locations = (
            self.location_dest_id
            or self.mat_destination_ids.mapped('location_id')
        ).ids
        quants = self.env['stock.quant'].sudo().browse()
        if dest_products and dest_locations:
            quants = self.env['stock.quant'].sudo().search([
                ('product_id', 'in', dest_products),
                ('location_id', 'child_of', dest_locations)
            ])
        return {
            'name': 'Stock Quants',
            'type': 'ir.actions.act_window',
            'res_model': 'stock.quant',
            'view_mode': 'list',
            'domain': [('id', 'in', quants.ids)],
            'context': {
                'create': 0,
                'edit': 0,
                'delete': 0,
                'duplicate': 0,
            }
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