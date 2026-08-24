from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging
import pytz
from datetime import timedelta
_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = 'stock.picking'
    
    sloc_filled = fields.Boolean(string="SLOC Filled", compute='_compute_sloc_filled', store=True)
    checker_only = fields.Boolean(related='picking_type_id.checker_only', store=True)
    checker_out = fields.Boolean(related='picking_type_id.checker_out', store=True)
    production_only = fields.Boolean(related='picking_type_id.production_only', store=True)
    detail_operation_scan = fields.Char(string="Detail Scan", store=True, compute='_compute_operation_scan')
    picking_type_bypass_entire_packs = fields.Boolean(related='picking_type_id.bypass_entire_packs', store=True)
    create_new_picking = fields.Boolean(related='picking_type_id.create_new_picking', store=True)
    autofill_pack_qty = fields.Boolean(related='picking_type_id.autofill_pack_qty', store=True)
    hide_zero_qty = fields.Boolean(related='picking_type_id.hide_zero_qty', store=True)
    uu_only = fields.Boolean(related='picking_type_id.uu_only', store=True)
    split_package = fields.Boolean(related='picking_type_id.split_package', store=True)
    hide_edit_barcode = fields.Boolean(related='picking_type_id.hide_edit_barcode', store=True)
    check_scan_pallet = fields.Boolean(related='picking_type_id.check_scan_pallet', store=True)
    bulk_pallet_lot = fields.Boolean(related='picking_type_id.bulk_pallet_lot', store=True)

    def _get_fields_stock_barcode(self):
        res = super()._get_fields_stock_barcode()
        if 'checker_only' not in res:
            res.append('checker_only')
        if 'checker_out' not in res:
            res.append('checker_out')
        if 'production_only' not in res:
            res.append('production_only')
        if 'picking_type_bypass_entire_packs' not in res:
            res.append('picking_type_bypass_entire_packs')
        if 'create_new_picking' not in res:
            res.append('create_new_picking')
        if 'autofill_pack_qty' not in res:
            res.append('autofill_pack_qty')
        if 'hide_zero_qty' not in res:
            res.append('hide_zero_qty')
        if 'uu_only' not in res:
            res.append('uu_only')
        if 'hide_edit_barcode' not in res:
            res.append('hide_edit_barcode')
        if 'split_package' not in res:
            res.append('split_package')
        if 'check_scan_pallet' not in res:
            res.append('check_scan_pallet')
        if 'bulk_pallet_lot' not in res:
            res.append('bulk_pallet_lot')
        return res
    
    def _get_stock_barcode_data(self):
        data = super()._get_stock_barcode_data()
        
        # ini untuk autofill
        move_lines = self.move_line_ids
        products = self.move_ids.product_id | move_lines.product_id
        extra_uoms = (
            products.uom_bag_id
            | products.uom_pallet_id
            | move_lines.uom_bag_id
            | move_lines.uom_pallet_id
        )
        if extra_uoms:
            existing_uom_ids = {rec['id'] for rec in data['records'].get('uom.uom', [])}
            new_uoms = extra_uoms.filtered(lambda u: u.id not in existing_uom_ids)
            if new_uoms:
                data['records']['uom.uom'] += new_uoms.read(new_uoms._get_fields_stock_barcode(), load=False)
        
        if self.production_only:
            production_lines = self.env['production.line'].sudo().search([
                ('active', '=', True),
                ('company_id', 'in', [self.company_id.id, False]),
            ])
            data['records']['production.line'] = production_lines.read(
                production_lines._get_fields_stock_barcode(), load=False
            )
        return data
    
    @api.depends('product_packaging_ids.sloc_id')
    def _compute_sloc_filled(self):
        for rec in self:
            lines = rec.product_packaging_ids
            rec.sloc_filled = bool(lines) and all(l.sloc_id for l in lines)
            
    @api.depends('move_line_ids.package_id')
    def _compute_operation_scan(self):
        for rec in self:
            detail_scan = []
            for line in rec.move_line_ids:
                source_package = line.package_id.name or '-'
                product = line.product_id.default_code or '-'
                detail_scan.append(f"{source_package} - {product}")
            rec.detail_operation_scan = "\n".join(detail_scan)
    
    def action_open_sloc_packaging_wizard(self):
        self.ensure_one()

        view = self.env.ref('wms_inherit_stock_barcode.view_sloc_packaging_wizard_form')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Set SLOC Packaging',
            'res_model': 'sloc.barcode',
            'views': [(view.id, 'form')],
            'target': 'new',
            'context': {
                'default_picking_id': self.id,
            }
        }
        
    def action_open_quality_backorder(self):
        self.ensure_one()
        
        active_line_id = self.env.context.get('active_line_id')
        if active_line_id:
            lines_to_process = self.move_line_ids.filtered(lambda l: l.id == active_line_id)
        else:
            lines_to_process = self.move_line_ids
            
        view = self.env.ref('wms_inherit_stock_barcode.view_quality_quantity_backorder_wizard_form')
        default_picking = False
        if self.checker_only:
            default_picking = self.picking_type_id.quality_type_id.id
        if self.checker_out:
            default_picking = self.picking_type_id.quality_out_type_id.id
            
        return {
            'type': 'ir.actions.act_window',
            'name': 'Set QQ Backorder',
            'res_model': 'quality.quantity.backorder',
            'views': [(view.id, 'form')],
            'target': 'new',
            'context': {
                'default_picking_id': self.id,
                'default_picking_type_id': default_picking or False,
                'default_line_ids': [(0, 0, {
                    'backorder_wizard_id': 0,
                    'move_line_id': line.id or False,
                    'product_id': line.product_id.id or False,
                    'limit_qty_pack': line.bag_qty if line.bag_qty > 0 else ((line.quantity * line.product_uom_id.factor) / 1000) / (line.uom_bag_id.factor / 1000),
                    # 'qty': line.quantity,
                    'product_uom_id': line.product_uom_id.id or False,
                    # 'qty_pack': line.bag_qty if line.bag_qty > 0 else ((line.quantity * line.product_uom_id.factor) / 1000) / (line.uom_bag_id.factor / 1000),
                    'pack_uom_id': line.uom_bag_id.id or False,
                    'location_id': line.location_id.id or False, 
                    'lot_id': line.lot_id.id or False, 
                    'package_id': line.package_id.id or False, 
                    'production_line_id': line.production_line_id.id or False, 
                    'company_id': line.company_id.id or False, 
                }) for line in lines_to_process],
                'default_is_quality': True,
            }
        }
    
    def action_open_quantity_backorder(self):
        self.ensure_one()

        view = self.env.ref('wms_inherit_stock_barcode.view_quality_quantity_backorder_wizard_form')
        default_picking = False
        if self.checker_only:
            default_picking = self.picking_type_id.quantity_type_id.id
        if self.checker_out:
            default_picking = self.picking_type_id.quantity_out_type_id.id
        return {
            'type': 'ir.actions.act_window',
            'name': 'Set QQ Backorder',
            'res_model': 'quality.quantity.backorder',
            'views': [(view.id, 'form')],
            'target': 'new',
            'context': {
                'default_picking_id': self.id,
                'default_picking_type_id': default_picking or False,
                'default_line_ids': [(0, 0, {
                    'backorder_wizard_id': 0,
                    'product_id': line.product_id.id,
                    'qty': line.bag_qty,
                    'product_uom_id': line.uom_bag_id.id,
                }) for line in self.move_ids ],
            }
        }
        
    def action_open_new_create_picking(self):
        self.ensure_one()
        if not self.sale_id:
            raise ValidationError(f"Tidak bisa melakukan New Picking karena tidak ada Sale Order pada {self.name}")
        
        view = self.env.ref('wms_inherit_stock_barcode.view_create_new_picking_wizard_form')
        
        active_line_id = self.env.context.get('active_line_id')
        lines_to_process = self.env['sale.order.line'].sudo()
        valid_so_lines = self.sale_id.order_line.filtered(lambda l: not l.display_type and l.product_id)

        if active_line_id:
            move_line = self.env['stock.move.line'].browse(active_line_id)
            if move_line.exists() and move_line.move_id.sale_line_id:
                lines_to_process = move_line.move_id.sale_line_id

        if not lines_to_process:
            lines_to_process = valid_so_lines
            
        default_lines = []
        for line in lines_to_process:
            uom_name = (line.product_uom_id.name or '').lower()
            if uom_name == 'kg':
                qty_kg = line.product_uom_qty
                if line.product_id.uom_bag_id:
                    qty_bag = line.product_uom_id._compute_quantity(line.product_uom_qty, line.product_id.uom_bag_id)
                else:
                    qty_bag = 0.0
            else:
                qty_bag = line.product_uom_qty
                qty_kg = line.product_uom_id._compute_quantity(line.product_uom_qty, line.product_id.uom_id)

            default_lines.append((0, 0, {
                'product_id': line.product_id.id or False,
                'qty': 0.0, 
                'product_uom_id': line.product_id.uom_id.id or False,
                'qty_pack': 0.0, 
                'pack_uom_id': line.product_id.uom_bag_id.id or False,
                'company_id': line.company_id.id or False, 
            }))

        return {
            'type': 'ir.actions.act_window',
            'name': 'Create New Picking',
            'res_model': 'create.new.picking',
            'views': [(view.id, 'form')],
            'target': 'new',
            'context': {
                'default_picking_id': self.id,
                'default_line_ids': default_lines
            }
        }
        
    def _prepare_packaging_lines_vals(self):
        Packaging = self.env['product.packaging.sap'].sudo()

        all_moves = self.mapped('move_ids').filtered(lambda m: m.product_id)
        if not all_moves:
            return []

        all_templates = all_moves.mapped('product_id.product_tmpl_id')

        packaging_data = Packaging.search([
            ('product_id', 'in', all_templates.ids),
            ('company_id', 'in', self.mapped('company_id').ids)
        ])

        packaging_map = {(p.product_id.id, p.company_id.id): p for p in packaging_data}

        origins = self.mapped('origin')
        origin_pickings = self.env['stock.picking'].sudo().search([('name', 'in', origins)])
        origin_map = {p.name: p for p in origin_pickings}

        create_vals = []

        for picking in self:
            moves = picking.move_ids.filtered(lambda m: m.product_id)
            if not moves:
                continue

            existing_products = set(picking.product_packaging_ids.mapped('product_id').ids)

            origin_picking = origin_map.get(picking.origin)

            sloc_map = {}
            if origin_picking:
                sloc_map = {
                    line.product_id.id: line.sloc_id.id
                    for line in origin_picking.product_packaging_ids
                    if line.sloc_id
                }

            packaging_type = picking.picking_type_id.packaging_type_id

            for move in moves:
                tmpl_id = move.product_id.product_tmpl_id.id

                if tmpl_id in existing_products:
                    continue

                packaging = packaging_map.get((tmpl_id, picking.company_id.id))
                if not packaging:
                    continue

                create_vals.append({
                    'picking_id': picking.id,
                    'product_id': tmpl_id,
                    'product_uom_desc': packaging.product_uom_desc,
                    'packaging_code': packaging.packaging_code,
                    'packaging_desc': packaging.packaging_desc,
                    'company_id': picking.company_id.id,
                    'packaging_type_id': packaging_type.id,
                    'move_type_sap': packaging_type.move_type_sap,
                    'sloc_id': sloc_map.get(tmpl_id),
                })

        return create_vals

    def _sync_packaging_lines(self):
        vals_list = self._prepare_packaging_lines_vals()
        if vals_list:
            self.env['picking.packaging.line'].create(vals_list)
    
    def _check_all_sloc_filled(self):
        for picking in self:
            if picking.picking_type_id.production_only:
                lines = picking.product_packaging_ids
                if not lines:
                    continue

    def _check_all_result_package_id(self):
        for picking in self:
            lines = picking.move_line_ids
            if not lines:
                continue
            
            if picking.picking_type_id.mandatory_destination:
                no_package = lines.filtered(lambda l: not l.result_package_id and l.quantity > 0)
                if no_package:
                    raise ValidationError(
                        f"Destination Package belum diisi untuk picking {picking.name}.\n\n"
                        f"Silahkan isi dahulu Destination Package pada : {', '.join(no_package.mapped('product_reference_code') or '-')}"
                    )
            if picking.production_only:
                no_production_line = lines.filtered(lambda l: not l.production_line_id and l.quantity > 0)
                if no_production_line:
                    raise ValidationError(
                        f"Production Line belum diisi untuk picking {picking.name}.\n\n"
                        f"Silahkan isi dahulu Production Line pada : {', '.join(no_production_line.mapped('product_reference_code') or '-')}"
                    )
                    
    def _sync_post_validate_quantities(self):
        for picking in self:
            if picking.state != 'done':
                continue

            is_updated = False
            for line in picking.move_line_ids:
                qty = line.qty_done if line.qty_done > 0 else line.quantity
                
                if qty > 0 and line.bag_qty <= 0 and line.pallet_qty <= 0:
                    new_bag_qty = 0.0
                    new_pallet_qty = 0.0
                    
                    if line.product_uom_id and line.product_uom_id.factor and line.uom_bag_id and line.uom_bag_id.factor:
                        new_bag_qty = ((qty * line.product_uom_id.factor) / 1000) / (line.uom_bag_id.factor / 1000)
                        
                    if line.uom_pallet_id and line.uom_pallet_id.factor:
                        new_pallet_qty = qty / (line.uom_pallet_id.factor / 1000)
                        
                    line.sudo().write({
                        'bag_qty': round(new_bag_qty),
                        'pallet_qty': new_pallet_qty
                    })
                    
                    is_updated = True
            
            if is_updated:
                picking.message_post(body="Bag dan Pallet Move Line otomatis terisi karena match kondisi")
    
    def _check_production_order_sap(self):
        for picking in self:
            if picking.picking_type_id.production_only and not picking.po_sap_id:
                raise ValidationError(f"Tidak bisa melakukan Validate karena {picking.picking_type_id.name} membutuhkan PO SAP")
            if picking.po_sap_id and (not picking.po_sap_id.active or picking.po_sap_id.state in ('teco', 'closed')):
                raise ValidationError("Tidak dapat melakukan Validate. PO SAP tidak aktif atau berstatus TECO!")
    
    def _create_backorder(self, backorder_moves=None):
        backorders = super()._create_backorder(backorder_moves=backorder_moves)
        # Backorders (mis. CO dengan create_backorder='always') tidak pernah
        # dijangkau oleh pemanggilan _fill_next_transfer_result_package() di
        # button_validate karena itu hanya melihat move_dest_ids, bukan
        # backorder. Panggil ulang di sini agar result_package_id tetap terisi.
        backorders._fill_next_transfer_result_package()
        return backorders

    def _fill_next_transfer_result_package(self):
        pickings = self.filtered(
            lambda p: p.picking_type_id.book_full_pallet
            and p.picking_type_id.code != 'outgoing'
            and not p.picking_type_id.split_package
        )
        for picking in pickings:
            for ml in picking.move_line_ids.filtered(lambda l: l.state not in ('done', 'cancel')):
                if not ml.result_package_id:
                    ml.write({'result_package_id': ml.package_id})
                    
    def _get_next_pallet_ke_map(self):
        result = {}
        tz_name = 'Asia/Jakarta'
        user_tz = pytz.timezone(tz_name)

        for rec in self:
            if not rec.picking_type_id.production_only or not rec.production_shift_id:
                continue
            
            # 1. Base time dari scheduled_date (support backdate)
            base_time = rec.scheduled_date if rec.scheduled_date else fields.Datetime.now()
            local_dt = pytz.utc.localize(base_time).astimezone(user_tz)
            
            shift_code = rec.production_shift_id.code or ''
            shift_name = rec.production_shift_id.name or ''
            
            # 2. Tentukan batas Start Shift lokal
            if shift_code == '0011' or 'Shift 1' in shift_name:
                if local_dt.hour >= 23:
                    start_local = local_dt.replace(hour=23, minute=0, second=0, microsecond=0)
                else:
                    start_local = (local_dt - timedelta(days=1)).replace(hour=23, minute=0, second=0, microsecond=0)
            elif shift_code == '0013' or 'Shift 3' in shift_name:
                start_local = local_dt.replace(hour=15, minute=0, second=0, microsecond=0)
            else:
                start_local = local_dt.replace(hour=7, minute=0, second=0, microsecond=0)
            
            # 3. Hitung end shift (+8 jam) & convert ke UTC untuk query database
            end_local = start_local + timedelta(hours=8)
            start_utc = start_local.astimezone(pytz.utc).replace(tzinfo=None)
            end_utc = end_local.astimezone(pytz.utc).replace(tzinfo=None)

            # 4. Kumpulkan group data move_line di memori
            groups = {}
            for ml in rec.move_line_ids:
                groups.setdefault((ml.product_id.id, ml.production_line_id.id), []).append(ml)

            # --- OPTIMASI KECEPATAN (PERFORMANCE TWEAK) ---
            # Kumpulkan semua list product_id dan production_line_id yang ada di dokumen ini
            product_ids = [k[0] for k in groups.keys() if k[0]]
            production_line_ids = [k[1] for k in groups.keys() if k[1]]

            # Buat 1 Query Domain (Mewakili seluruh item)
            domain = [
                ('picking_id', '!=', rec.id),
                ('picking_id.state', '=', 'done'),
                ('picking_id.picking_type_id.production_only', '=', True),
                ('picking_id.production_shift_id', '=', rec.production_shift_id.id),
                ('picking_id.po_sap_id', '=', rec.po_sap_id.id),
                ('product_id', 'in', product_ids),
                ('production_line_id', 'in', production_line_ids),
                ('picking_id.date_done', '>=', start_utc),
                ('picking_id.date_done', '<', end_utc),
            ]

            # Lakukan 'read_group' HANYA 1 KALI menembak database untuk mencari MAX(pallet_ke)
            grouped_data = self.env['stock.move.line'].sudo().read_group(
                domain,
                ['product_id', 'production_line_id', 'pallet_ke:max'],
                ['product_id', 'production_line_id'],
                lazy=False
            )

            # Map hasil read_group ke dictionary agar mudah dibaca
            max_pallet_map = {}
            for data in grouped_data:
                prod_id = data.get('product_id')[0] if data.get('product_id') else False
                pline_id = data.get('production_line_id')[0] if data.get('production_line_id') else False
                max_pallet_map[(prod_id, pline_id)] = data.get('pallet_ke') or 0

            # 5. Pasangkan/assign pallet_ke yang baru ke masing-masing move line
            for (product_id, production_line_id), mls in groups.items():
                # Ambil data max_pallet_ke dari dict, jika tidak ada berarti mulai dari 1
                current_max_pallet = max_pallet_map.get((product_id, production_line_id), 0)
                next_pallet = current_max_pallet + 1
                
                for ml in mls:
                    result[ml] = next_pallet
                    next_pallet += 1
                    
        return result
    
    def remove_package_customer_location(self):
        for picking in self:
            if picking.picking_type_id.default_location_dest_id.usage == 'customer': # 'outgoing'
                picking.move_line_ids.write({'result_package_id': False})
                picking.move_ids.write({'package_ids': [(5, 0, 0)]})
                
    def restrict_customer_location(self):
        for picking in self:
            if picking.picking_type_id.default_location_dest_id.usage == 'customer': # 'outgoing'
                if self.env.su or self.env.context.get('from_cron'):
                    continue
                
                if not self.env.user.has_group('stock.group_stock_manager'):
                    raise ValidationError("User biasa tidak bisa melakukan validate ke lokasi customer! Silahkan hubungi admin.")

    def split_restrict_upp(self):
        for picking in self.filtered(lambda p: p.split_package):
            valid_move_lines = picking.move_line_ids.filtered(lambda ml: ml.result_package_id != ml.package_id)
            if not valid_move_lines:
                continue

            package_ids = valid_move_lines.mapped('result_package_id.id')
            existing_quants = self.env['stock.quant'].sudo().search([
                ('package_id', 'in', package_ids),
                ('location_id.usage', '=', 'internal')
            ])

            existing_qty_map = {}
            for quant in existing_quants:
                key = (quant.package_id.id, quant.product_id.id, quant.lot_id.id)
                qty_lama = quant.pallet_qty if hasattr(quant, 'pallet_qty') else 0.0
                existing_qty_map[key] = existing_qty_map.get(key, 0.0) + qty_lama

            package_qty_map = {}
            for line in valid_move_lines:
                key = (line.result_package_id.id, line.product_id.id, line.lot_id.id)
                if key not in package_qty_map:
                    package_qty_map[key] = {
                        'total_pallet_qty': existing_qty_map.get(key, 0.0), 
                        'product_code': line.product_id.default_code or line.product_id.name,
                        'package_name': line.result_package_id.name,
                        'lot_name': line.lot_id.name or 'No Lot' # Untuk pesan error
                    }
                
                package_qty_map[key]['total_pallet_qty'] += line.pallet_qty

            for data in package_qty_map.values():
                if round(data['total_pallet_qty'], 5) > 1.0:
                    raise ValidationError(
                        f"Quantity pada product {data['product_code']} (Lot: {data['lot_name']}) "
                        f"di package {data['package_name']} melebihi UPP Pallet pada proses "
                        f"Split Package (Total saat ini: {data['total_pallet_qty']})."
                    )

    def button_validate(self):
        self._sync_packaging_lines()
        # self._check_all_sloc_filled()
        self._check_all_result_package_id()
        self._check_production_order_sap()
        self.remove_package_customer_location()
        self.restrict_customer_location()
        # self.split_restrict_upp()
        if self.checker_only or self.checker_out:
            status, product, diff_qty = self._has_missing_qty()
            konversi = False
            if product:
                konversi = product.uom_id._compute_quantity(diff_qty, product.uom_bag_id)
            if status == 'missing':
                raise ValidationError("Silahkan lakukan Check Quantity untuk melanjutkan proses Validate")
            elif status == 'excess':
                raise ValidationError(f"Quantity yang dimasukkan melebihi Quantity Inbound sebanyak [{konversi} {product.uom_bag_id.name}]")

        res = super().button_validate()
        if not isinstance(res, dict):
            self._sync_post_validate_quantities()
            next_pickings = self.sudo().mapped('move_ids.move_dest_ids.picking_id').filtered(lambda p: p)
            if next_pickings:
                next_pickings._sync_packaging_lines()
                next_pickings._fill_next_transfer_result_package()
            self.move_line_ids._check_package_capacity_limit()
        return res
    
    def _pre_action_done_hook(self):
        res = super()._pre_action_done_hook()
        if res is not True:
            return res 

        if self.picking_type_id.production_only:
            pallet_map = self._get_next_pallet_ke_map()

            if self.env.context.get('pallet_ke_confirmed'):
                for ml, next_pallet in pallet_map.items():
                    ml.pallet_ke = next_pallet
                return True

            if pallet_map:
                message_lines = [
                    f"- {ml.product_id.display_name}: Pallet Ke-{next_pallet}"
                    for ml, next_pallet in pallet_map.items()
                ]
                msg = "Anda akan mengkonfirmasi data pallet berikut:\n" + "\n".join(message_lines)

                wizard = self.env['production.pallet.wizard'].sudo().create({
                    'picking_id': self.id,
                    'message': msg,
                })

                return {
                    'name': 'Konfirmasi Nomor Pallet',
                    'type': 'ir.actions.act_window',
                    'res_model': 'production.pallet.wizard',
                    'res_id': wizard.id,
                    'view_mode': 'form',
                    'views': [(False, 'form')],
                    'target': 'new',
                }

        return True
    
    def _has_missing_qty(self):
        root_picking = self
        while root_picking.backorder_id:
            root_picking = root_picking.backorder_id

        def get_all_pickings_in_chain(root):
            result = root
            # children = self.env['stock.picking'].sudo().search([('backorder_id', '=', root.id)])
            # for child in children:
            #     result |= get_all_pickings_in_chain(child)
            return result

        all_related_pickings = get_all_pickings_in_chain(root_picking)
        
        for move in self.move_ids:
            product = move.product_id
            root_moves_line = root_picking.move_line_ids.filtered(lambda m: m.product_id == product)
            total_demand = sum(root_moves_line.mapped('quantity'))
            all_moves_in_chain = all_related_pickings.mapped('move_line_ids').filtered(lambda m: m.product_id == product)
            total_processed = sum(all_moves_in_chain.mapped('quantity'))
            if total_demand > total_processed:
                return 'missing', product, (total_demand - total_processed)
            if total_demand < total_processed:
                return 'excess', product, (total_processed - total_demand)
        return 'ok', None, 0.0
    
    # Quantity Backorder YANG PAKE DEMAND
    def action_create_quantity_backorder(self):
        self.ensure_one()

        if not (self.checker_only or self.checker_out):
            return

        # 1. Root picking
        root_picking = self
        while root_picking.backorder_id:
            root_picking = root_picking.backorder_id

        _logger.info(f"[DEBUG-QTY] Root Picking: {root_picking.name}")

        processed_pairs = set()

        for ml in self.move_line_ids:
            product = ml.product_id
            package = ml.package_id
            lot = ml.lot_id
            location = ml.location_id # Sangat penting untuk mencari Quant yang tepat

            # Tambahkan location ke dalam key agar komparasi akurat per lokasi
            pair_key = (product.id, package.id if package else False, lot.id if lot else False, location.id)
            if pair_key in processed_pairs:
                continue
            processed_pairs.add(pair_key)

            _logger.info(f"[DEBUG-QTY] --- Analisa Produk: {product.display_name} | Package: {package.name if package else 'No Package'} ---")

            # 1. CARI LANGSUNG KE STOCK.QUANT
            # Kita tidak lagi melihat dokumen awal, tapi melihat FISIK BARANG yang tersisa
            all_quants = self.env['stock.quant'].sudo().search([
                ('location_id', '=', location.id),
                ('product_id', '=', product.id),
                ('lot_id', '=', lot.id if lot else False),
                ('package_id', '=', package.id if package else False),
            ])
            
            total_available_qty = 0.0
            usable_quants = []
            
            for q in all_quants:
                # Menghitung sisa berdasarkan log Anda: auto_apply (1240) - reserved (1220) = 20
                avail = q.quantity - q.reserved_quantity
                _logger.info(f"[DEBUG-QTY] Quant ID {q.id} -> Total: {q.quantity}, Reserved: {q.reserved_quantity}, Available: {avail}")
                
                if avail > 0:
                    total_available_qty += avail
                    usable_quants.append(q)
            
            # Sisa qty inilah yang akan menjadi missing_qty (20)
            missing_qty = total_available_qty
            
            _logger.info(f"[DEBUG-QTY] Total Sisa di Quant (missing_qty): {missing_qty}")

            # 2. EKSEKUSI PEMBUATAN PICKING JIKA ADA SISA DI QUANT
            if missing_qty > 0:
                qty_type = False
                if self.checker_only:
                    qty_type = self.picking_type_id.quantity_type_id
                if self.checker_out:
                    qty_type = self.picking_type_id.quantity_out_type_id
                
                if not qty_type:
                    raise UserError("Operation type tidak memiliki Quantity Type.")
                
                usable_quants = sorted(
                    usable_quants,
                    key=lambda q: (q.quantity - q.reserved_quantity),
                    reverse=True,
                )

                new_picking = self.env['stock.picking'].create({
                    'picking_type_id': qty_type.id,
                    'location_id': location.id,
                    'location_dest_id': qty_type.default_location_dest_id.id,
                    'company_id': self.company_id.id,
                    'backorder_id': root_picking.id,
                    'origin': f"{root_picking.name} - Qty Remaining",
                    'po_sap_id': self.po_sap_id.id if hasattr(self, 'po_sap_id') and self.po_sap_id else False,
                })

                parent_move = ml.move_id
                new_move = self.env['stock.move'].create({
                    'picking_id': new_picking.id,
                    'product_id': product.id,
                    'product_uom_qty': missing_qty, 
                    'product_uom': ml.product_uom_id.id,
                    'location_id': location.id,
                    'location_dest_id': new_picking.location_dest_id.id,
                    'company_id': self.company_id.id,
                    'sale_line_id': parent_move.sale_line_id.id if hasattr(parent_move, 'sale_line_id') and parent_move.sale_line_id else False,
                    'purchase_line_id': parent_move.purchase_line_id.id if hasattr(parent_move, 'purchase_line_id') and parent_move.purchase_line_id else False,
                    'sap_seq': parent_move.sap_seq if hasattr(parent_move, 'sap_seq') else False,
                    'order_seq': parent_move.order_seq if hasattr(parent_move, 'order_seq') else False,
                    'order_selection': parent_move.order_selection if hasattr(parent_move, 'order_selection') else False,
                })
                new_move._action_confirm()

                if new_move.move_line_ids:
                    new_move.move_line_ids.unlink()

                remaining = missing_qty 
                created_lines = []

                for q in usable_quants:
                    if remaining <= 0:
                        break

                    avail = q.quantity - q.reserved_quantity
                    take_qty = min(avail, remaining)

                    ml_vals = {
                        'move_id': new_move.id,
                        'picking_id': new_picking.id,
                        'product_id': product.id,
                        'product_uom_id': ml.product_uom_id.id,
                        'quantity': take_qty,
                        'lot_id': q.lot_id.id if q.lot_id else False,
                        'location_id': location.id,
                        'location_dest_id': new_picking.location_dest_id.id,
                        'package_id': q.package_id.id if q.package_id else False,
                        'result_package_id': False,
                        'stock_type': getattr(q, 'stock_type', 'QI'),
                    }
                    new_ml = self.env['stock.move.line'].create(ml_vals)
                    created_lines.append({
                        'ml_id': new_ml.id,
                        'quant_id': q.id,
                        'package_id': q.package_id.id if q.package_id else None,
                        'take_qty': take_qty,
                        'avail_was': avail,
                    })
                    remaining -= take_qty

                try:
                    new_picking.with_context(
                        skip_backorder=True,
                        skip_immediate=True,
                        skip_sms=True,
                    ).button_validate()
                except Exception as e:
                    _logger.error(f"[GRGI] qty_backorder picking={new_picking.name} button_validate FAILED: {e}")
                    raise

                if new_picking.state != 'done':
                    try:
                        new_move.with_context(
                            skip_backorder=True,
                            skip_immediate=True,
                        )._action_done()
                    except Exception as e2:
                        _logger.error(f"[GRGI] qty_backorder picking={new_picking.name} _action_done FAILED: {e2}")
                        raise

                if new_picking.state != 'done':
                    raise UserError(f"Picking {new_picking.name} gagal divalidasi otomatis.")

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Success",
                "message": "Qty Backorder telah diproses.",
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
    