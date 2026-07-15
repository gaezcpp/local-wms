from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging
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
        _logger.info("EXTRA UOMS: %s", extra_uoms.ids)
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

        lines_to_process = self.sale_id.order_line.filtered(lambda l: not l.display_type)
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
                'qty': qty_kg, 
                'product_uom_id': line.product_id.uom_id.id or False,
                'qty_pack': qty_bag, 
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

                # missing = lines.filtered(lambda l: not l.sloc_id)
                # if missing:
                    # raise ValidationError(
                    #     f"SLOC belum lengkap untuk picking {picking.name}.\n\n"
                    #     f"Masukkan SLOC Packaging pada : {', '.join(missing.mapped('packaging_desc'))}"
                    # )
    
    def _check_all_result_package_id(self):
        for picking in self:
            lines = picking.move_line_ids
            if not lines:
                continue
            
            if picking.picking_type_id.mandatory_destination:
                no_package = lines.filtered(lambda l: not l.result_package_id)
                if no_package:
                    raise ValidationError(
                        f"Destination Package belum diisi untuk picking {picking.name}.\n\n"
                        f"Silahkan isi dahulu Destination Package pada : {', '.join(no_package.mapped('product_reference_code') or '-')}"
                    )
            if picking.production_only:
                no_production_line = lines.filtered(lambda l: not l.production_line_id)
                if no_production_line:
                    raise ValidationError(
                        f"Production Line belum diisi untuk picking {picking.name}.\n\n"
                        f"Silahkan isi dahulu Production Line pada : {', '.join(no_package.mapped('product_reference_code') or '-')}"
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
    
    def button_validate(self):
        self._sync_packaging_lines()
        self._check_all_sloc_filled()
        self._check_all_result_package_id()
        self._check_production_order_sap()
        if self.checker_only or self.checker_out:
            status, product, diff_qty = self._has_missing_qty()
            konversi = False
            if product:
                konversi = product.uom_id._compute_quantity(diff_qty, product.uom_bag_id)
            if status == 'missing':
                raise ValidationError("Silahkan lakukan Check Quantity untuk melanjutkan proses Validate")
            elif status == 'excess':
                raise ValidationError(f"Quantity yang dimasukkan melebihi Quantity Inbound sebanyak [{konversi} {product.uom_bag_id.name}]")
            
            # for move in self.move_ids:
            #     if move.state in ('cancel', 'done'):
            #         continue
            #     total_bag_qty = sum(move.move_line_ids.mapped('bag_qty'))
            #     if total_bag_qty <= 0.0:
            #         raise ValidationError(f"Tidak bisa melakukan Validate: Pack Quantity untuk produk {move.product_id.name} karena masih 0. ")
        res = super().button_validate()
        self._sync_post_validate_quantities()
        next_pickings = self.sudo().mapped('move_ids.move_dest_ids.picking_id').filtered(lambda p: p)
        if next_pickings:
            next_pickings._sync_packaging_lines()
        return res
    
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
            _logger.info(f"APAKAH HAS MISSING DEMAND {total_demand} | PROCESSED {total_processed}")
            if total_demand > total_processed:
                return 'missing', product, (total_demand - total_processed)
            if total_demand < total_processed:
                return 'excess', product, (total_processed - total_demand)
        return 'ok', None, 0.0
        
        # for move in self.move_ids:
        #     product = move.product_id
        #     root_moves = root_picking.move_ids.filtered(lambda m: m.product_id == product)
        #     total_demand = sum(root_moves.mapped('product_uom_qty'))
        #     all_moves_in_chain = all_related_pickings.mapped('move_ids').filtered(lambda m: m.product_id == product)
        #     total_processed = sum(all_moves_in_chain.mapped('move_line_ids.quantity'))
        #     _logger.info(f"APAKAH HAS MISSING DEMAND {total_demand} | PROCESSED {total_processed}")
        #     if total_demand > total_processed:
        #         return 'missing', product, (total_demand - total_processed)
        #     if total_demand < total_processed:
        #         return 'excess', product, (total_processed - total_demand)
        # return 'ok', None, 0.0
    
    # Quantity Backorder
    # def action_create_quantity_backorder(self):
    #     self.ensure_one()
    #     _logger.info(f"=== START action_create_quantity_backorder for {self.name} ===")

    #     if not (self.checker_only or self.checker_out):
    #         _logger.info(f"NOT CHECKER ONLY {self.checker_only} atau CHECKER OUT {self.checker_out} SKIPPED")
    #         return

    #     # 1. Root picking
    #     root_picking = self
    #     while root_picking.backorder_id:
    #         root_picking = root_picking.backorder_id
    #     _logger.info(f"Root picking: {root_picking.name}")

    #     # 2. Semua picking dalam chain (rekursif)
    #     def get_all_pickings_in_chain(root):
    #         result = root
    #         children = self.env['stock.picking'].search([('backorder_id', '=', root.id)])
    #         for child in children:
    #             result |= get_all_pickings_in_chain(child)
    #         return result

    #     all_related_pickings = get_all_pickings_in_chain(root_picking)
    #     _logger.info(f"All pickings in chain: {[(p.name, p.state) for p in all_related_pickings]}")

    #     for move in self.move_ids:
    #         product = move.product_id
    #         _logger.info(f"--- Processing product: {product.name} ---")

    #         # Demand
    #         root_moves = root_picking.move_ids.filtered(lambda m: m.product_id == product)
    #         demand = sum(root_moves.mapped('product_uom_qty'))
    #         _logger.info(f"  Demand: {demand}")

    #         # Hitung total processed
    #         all_moves_in_chain = all_related_pickings.mapped('move_ids').filtered(lambda m: m.product_id == product)
    #         total_done = 0.0
    #         total_in_progress = 0.0
    #         for m in all_moves_in_chain:
    #             ml_qty_sum = sum(m.move_line_ids.mapped('quantity'))
    #             if m.state == 'done':
    #                 total_done += m.quantity
    #                 _logger.info(f"    [DONE] Move {m.id} | {m.picking_id.name} | qty: {m.quantity}")
    #             elif m.state not in ('cancel',):
    #                 total_in_progress += ml_qty_sum
    #                 _logger.info(
    #                     f"    [IN-PROGRESS] Move {m.id} | {m.picking_id.name} "
    #                     f"| state: {m.state} | ml_qty: {ml_qty_sum}"
    #                 )

    #         missing_qty = demand - (total_done + total_in_progress)
    #         _logger.info(
    #             f"  SUMMARY → demand: {demand} | done: {total_done} "
    #             f"| in_progress: {total_in_progress} | missing: {missing_qty}"
    #         )

    #         if missing_qty <= 0:
    #             _logger.info("  No missing qty, skipping.")
    #             continue

    #         qty_type = False
    #         if self.checker_only:
    #             qty_type = self.picking_type_id.quantity_type_id
    #         if self.checker_out:
    #             qty_type = self.picking_type_id.quantity_out_type_id
            
    #         if not qty_type:
    #             raise UserError(f"Operation type tidak memiliki Quantity Type.")

    #         # =====================================================================
    #         # CARI QUANT TERSEDIA YANG BENAR
    #         #
    #         # FIX dari iterasi sebelumnya:
    #         # - Jangan filter berdasarkan "apakah package ada di move_line aktif"
    #         #   karena package bisa ada di move_line aktif TAPI masih punya sisa
    #         #   available (quantity - reserved_quantity > 0)
    #         # - Filter yang benar: available_qty = quantity - reserved_quantity > 0
    #         # - Package conflict TIDAK terjadi jika kita mengambil dari available qty
    #         #   yang memang belum direservasi oleh siapapun
    #         # =====================================================================
    #         lot_id_for_search = move.move_line_ids[:1].lot_id.id if move.move_line_ids else False

    #         all_quants = self.env['stock.quant'].search([
    #             ('location_id', '=', move.location_id.id),
    #             ('product_id', '=', product.id),
    #             ('lot_id', '=', lot_id_for_search),
    #             ('quantity', '>', 0),
    #         ])
    #         _logger.info(f"  Semua quant di source location {move.location_id.name}:")
    #         for q in all_quants:
    #             avail = q.quantity - q.reserved_quantity
    #             _logger.info(
    #                 f"    Quant {q.id} | pkg: {q.package_id.name if q.package_id else 'None'} "
    #                 f"(id:{q.package_id.id if q.package_id else '-'}) "
    #                 f"| qty: {q.quantity} | reserved: {q.reserved_quantity} "
    #                 f"| available: {avail}"
    #             )

    #         # Filter: hanya yang benar-benar available (belum penuh direservasi)
    #         usable_quants = sorted(
    #             [q for q in all_quants if (q.quantity - q.reserved_quantity) > 0],
    #             key=lambda q: (q.quantity - q.reserved_quantity),
    #             reverse=True,
    #         )

    #         _logger.info(
    #             f"  Quant yang available (qty-reserved > 0): "
    #             f"{[(q.id, q.package_id.id if q.package_id else None, round(q.quantity - q.reserved_quantity, 2)) for q in usable_quants]}"
    #         )

    #         # Buat picking baru
    #         new_picking = self.env['stock.picking'].create({
    #             'picking_type_id': qty_type.id,
    #             'location_id': move.location_id.id,
    #             'location_dest_id': qty_type.default_location_dest_id.id,
    #             'company_id': self.company_id.id,
    #             'backorder_id': root_picking.id,
    #             'origin': f"{root_picking.name} - Qty Remaining",
    #             'po_sap_id': self.po_sap_id.id if self.po_sap_id else False,
    #         })
    #         _logger.info(f"  Created new picking: {new_picking.name}")

    #         new_move = self.env['stock.move'].create({
    #             'picking_id': new_picking.id,
    #             'product_id': product.id,
    #             'product_uom_qty': missing_qty,
    #             'product_uom': move.product_uom.id,
    #             'location_id': move.location_id.id,
    #             'location_dest_id': new_picking.location_dest_id.id,
    #             'company_id': self.company_id.id,
    #         })
    #         new_move._action_confirm()
    #         _logger.info(f"  Move {new_move.id} confirmed. State: {new_move.state}")

    #         # Hapus auto-generated move_line
    #         if new_move.move_line_ids:
    #             _logger.info(f"  Unlinking {len(new_move.move_line_ids)} auto move_line(s)")
    #             new_move.move_line_ids.unlink()

    #         # =====================================================================
    #         # BUAT MOVE_LINE DARI QUANT YANG AVAILABLE
    #         # Pakai package_id asli dari quant agar Odoo bisa track dengan benar
    #         # dan tidak membuat quant negatif
    #         # =====================================================================
    #         remaining = missing_qty
    #         created_lines = []

    #         for q in usable_quants:
    #             if remaining <= 0:
    #                 break

    #             avail = q.quantity - q.reserved_quantity
    #             take_qty = min(avail, remaining)

    #             ml_vals = {
    #                 'move_id': new_move.id,
    #                 'picking_id': new_picking.id,
    #                 'product_id': product.id,
    #                 'product_uom_id': move.product_uom.id,
    #                 'quantity': take_qty,
    #                 'lot_id': q.lot_id.id if q.lot_id else False,
    #                 'location_id': move.location_id.id,
    #                 'location_dest_id': new_picking.location_dest_id.id,
    #                 'package_id': q.package_id.id if q.package_id else False,
    #                 'result_package_id': False,
    #                 'stock_type': q.stock_type or 'QI',
    #             }
    #             ml = self.env['stock.move.line'].create(ml_vals)
    #             created_lines.append({
    #                 'ml_id': ml.id,
    #                 'quant_id': q.id,
    #                 'package_id': q.package_id.id if q.package_id else None,
    #                 'take_qty': take_qty,
    #                 'avail_was': avail,
    #             })
    #             _logger.info(
    #                 f"  Created move_line {ml.id}: ambil {take_qty} dari quant {q.id} "
    #                 f"(pkg: {q.package_id.name if q.package_id else 'None'}, "
    #                 f"avail was: {avail})"
    #             )
    #             remaining -= take_qty

    #         _logger.info(f"  Move lines created: {created_lines}")
    #         _logger.info(f"  Remaining unassigned after quant loop: {remaining}")

    #         if remaining > 0:
    #             # Ini kondisi KRITIS: tidak ada quant available sama sekali
    #             # Jangan buat move_line tanpa package — akan pasti bikin quant negatif
    #             # Raise error yang informatif
    #             _logger.error(
    #                 f"  KRITIS: Tidak ada quant tersedia untuk {remaining} qty! "
    #                 f"Total available dari semua quant: "
    #                 f"{sum(q.quantity - q.reserved_quantity for q in all_quants)}"
    #             )
    #             raise UserError(
    #                 f"Tidak cukup stok tersedia untuk membuat Qty Backorder.\n"
    #                 f"Produk: {product.display_name}\n"
    #                 f"Dibutuhkan: {missing_qty} | Tersedia: {missing_qty - remaining}\n"
    #                 f"Periksa stock quant di lokasi {move.location_id.name}."
    #             )

    #         # Validasi
    #         _logger.info(f"  Attempting button_validate() on {new_picking.name}...")
    #         try:
    #             result = new_picking.with_context(
    #                 skip_backorder=True,
    #                 skip_immediate=True,
    #                 skip_sms=True,
    #             ).button_validate()
    #             _logger.info(
    #                 f"  button_validate() returned: {result} | State: {new_picking.state}"
    #             )
    #         except Exception as e:
    #             _logger.error(f"  button_validate() FAILED: {e}")
    #             raise

    #         if new_picking.state != 'done':
    #             _logger.warning(
    #                 f"  {new_picking.name} masih {new_picking.state}. "
    #                 f"Fallback: move._action_done()..."
    #             )
    #             try:
    #                 new_move.with_context(
    #                     skip_backorder=True,
    #                     skip_immediate=True,
    #                 )._action_done()
    #                 _logger.info(
    #                     f"  move._action_done() selesai. "
    #                     f"Move: {new_move.state} | Picking: {new_picking.state}"
    #                 )
    #             except Exception as e2:
    #                 _logger.error(f"  move._action_done() FAILED: {e2}")
    #                 raise

    #         _logger.info(
    #             f"  FINAL: {new_picking.name} state={new_picking.state} | "
    #             f"move state={new_move.state}"
    #         )

    #         if new_picking.state != 'done':
    #             raise UserError(f"Picking {new_picking.name} gagal divalidasi otomatis.")

    #     _logger.info(f"=== END action_create_quantity_backorder for {self.name} ===")

    #     return {
    #         "type": "ir.actions.client",
    #         "tag": "display_notification",
    #         "params": {
    #             "title": "Success",
    #             "message": "Qty Backorder telah diproses.",
    #             "type": "success",
    #             "sticky": False,
    #             "next": {"type": "ir.actions.act_window_close"},
    #         },
    #     }
    
    # Quantity Backorder
    def action_create_quantity_backorder(self):
        self.ensure_one()
        _logger.info(f"=== START action_create_quantity_backorder for {self.name} ===")

        if not (self.checker_only or self.checker_out):
            _logger.info(f"NOT CHECKER ONLY {self.checker_only} atau CHECKER OUT {self.checker_out} SKIPPED")
            return

        # 1. Root picking
        root_picking = self
        while root_picking.backorder_id:
            root_picking = root_picking.backorder_id
        _logger.info(f"Root picking: {root_picking.name}")

        # 2. Semua picking dalam chain (rekursif)
        def get_all_pickings_in_chain(root):
            result = root
            children = self.env['stock.picking'].sudo().search([('backorder_id', '=', root.id)])
            for child in children:
                result |= get_all_pickings_in_chain(child)
            return result

        all_related_pickings = get_all_pickings_in_chain(root_picking)
        _logger.info(f"All pickings in chain: {[(p.name, p.state) for p in all_related_pickings]}")

        for move in self.move_ids:
            product = move.product_id
            _logger.info(f"--- Processing product: {product.name} ---")

            # Demand
            root_moves = root_picking.move_ids.filtered(lambda m: m.product_id == product)
            demand = sum(root_moves.mapped('product_uom_qty'))
            _logger.info(f"  Demand: {demand}")

            # Hitung total processed
            all_moves_in_chain = all_related_pickings.mapped('move_ids').filtered(lambda m: m.product_id == product)
            total_done = 0.0
            total_in_progress = 0.0
            for m in all_moves_in_chain:
                ml_qty_sum = sum(m.move_line_ids.mapped('quantity'))
                if m.state == 'done':
                    total_done += m.quantity
                    _logger.info(f"    [DONE] Move {m.id} | {m.picking_id.name} | qty: {m.quantity}")
                elif m.state not in ('cancel',):
                    total_in_progress += ml_qty_sum
                    _logger.info(
                        f"    [IN-PROGRESS] Move {m.id} | {m.picking_id.name} "
                        f"| state: {m.state} | ml_qty: {ml_qty_sum}"
                    )

            missing_qty = demand - (total_done + total_in_progress)
            _logger.info(
                f"  SUMMARY → demand: {demand} | done: {total_done} "
                f"| in_progress: {total_in_progress} | missing: {missing_qty}"
            )

            if missing_qty <= 0:
                _logger.info("  No missing qty, skipping.")
                continue
            
            if root_moves:
                target_move = root_moves[0]
                old_demand = target_move.product_uom_qty
                new_demand = max(old_demand - missing_qty, 0.0)
                _logger.info(
                    f"  Mengurangi demand root move {target_move.id} ({product.name}): "
                    f"{old_demand} -> {new_demand} (dialihkan ke backorder: {missing_qty})"
                )
                target_move.write({'product_uom_qty': new_demand})

            qty_type = False
            if self.checker_only:
                qty_type = self.picking_type_id.quantity_type_id
            if self.checker_out:
                qty_type = self.picking_type_id.quantity_out_type_id
            
            if not qty_type:
                raise UserError(f"Operation type tidak memiliki Quantity Type.")

            # =====================================================================
            # CARI QUANT TERSEDIA YANG BENAR
            # =====================================================================
            lot_id_for_search = move.move_line_ids[:1].lot_id.id if move.move_line_ids else False

            all_quants = self.env['stock.quant'].sudo().search([
                ('location_id', '=', move.location_id.id),
                ('product_id', '=', product.id),
                ('lot_id', '=', lot_id_for_search),
                ('quantity', '>', 0),
            ])
            _logger.info(f"  Semua quant di source location {move.location_id.name}:")
            for q in all_quants:
                avail = q.quantity - q.reserved_quantity
                _logger.info(
                    f"    Quant {q.id} | pkg: {q.package_id.name if q.package_id else 'None'} "
                    f"(id:{q.package_id.id if q.package_id else '-'}) "
                    f"| qty: {q.quantity} | reserved: {q.reserved_quantity} "
                    f"| available: {avail}"
                )

            # Filter: hanya yang benar-benar available (belum penuh direservasi)
            usable_quants = sorted(
                [q for q in all_quants if (q.quantity - q.reserved_quantity) > 0],
                key=lambda q: (q.quantity - q.reserved_quantity),
                reverse=True,
            )

            _logger.info(
                f"  Quant yang available (qty-reserved > 0): "
                f"{[(q.id, q.package_id.id if q.package_id else None, round(q.quantity - q.reserved_quantity, 2)) for q in usable_quants]}"
            )

            # Buat picking baru
            new_picking = self.env['stock.picking'].create({
                'picking_type_id': qty_type.id,
                'location_id': move.location_id.id,
                'location_dest_id': qty_type.default_location_dest_id.id,
                'company_id': self.company_id.id,
                'backorder_id': root_picking.id,
                'origin': f"{root_picking.name} - Qty Remaining",
                'po_sap_id': self.po_sap_id.id if self.po_sap_id else False,
            })
            _logger.info(f"  Created new picking: {new_picking.name}")

            new_move = self.env['stock.move'].create({
                'picking_id': new_picking.id,
                'product_id': product.id,
                'product_uom_qty': missing_qty,
                'product_uom': move.product_uom.id,
                'location_id': move.location_id.id,
                'location_dest_id': new_picking.location_dest_id.id,
                'company_id': self.company_id.id,
            })
            new_move._action_confirm()
            _logger.info(f"  Move {new_move.id} confirmed. State: {new_move.state}")

            # Hapus auto-generated move_line
            if new_move.move_line_ids:
                _logger.info(f"  Unlinking {len(new_move.move_line_ids)} auto move_line(s)")
                new_move.move_line_ids.unlink()

            # =====================================================================
            # BUAT MOVE_LINE DARI QUANT YANG AVAILABLE
            # =====================================================================
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
                    'product_uom_id': move.product_uom.id,
                    'quantity': take_qty,
                    'lot_id': q.lot_id.id if q.lot_id else False,
                    'location_id': move.location_id.id,
                    'location_dest_id': new_picking.location_dest_id.id,
                    'package_id': q.package_id.id if q.package_id else False,
                    'result_package_id': False,
                    'stock_type': q.stock_type or 'QI',
                }
                ml = self.env['stock.move.line'].create(ml_vals)
                created_lines.append({
                    'ml_id': ml.id,
                    'quant_id': q.id,
                    'package_id': q.package_id.id if q.package_id else None,
                    'take_qty': take_qty,
                    'avail_was': avail,
                })
                _logger.info(
                    f"  Created move_line {ml.id}: ambil {take_qty} dari quant {q.id} "
                    f"(pkg: {q.package_id.name if q.package_id else 'None'}, "
                    f"avail was: {avail})"
                )
                remaining -= take_qty

            _logger.info(f"  Move lines created: {created_lines}")
            _logger.info(f"  Remaining unassigned after quant loop: {remaining}")

            if remaining > 0:
                _logger.error(
                    f"  KRITIS: Tidak ada quant tersedia untuk {remaining} qty! "
                    f"Total available dari semua quant: "
                    f"{sum(q.quantity - q.reserved_quantity for q in all_quants)}"
                )
                raise UserError(
                    f"Tidak cukup stok tersedia untuk membuat Qty Backorder.\n"
                    f"Produk: {product.display_name}\n"
                    f"Dibutuhkan: {missing_qty} | Tersedia: {missing_qty - remaining}\n"
                    f"Periksa stock quant di lokasi {move.location_id.name}."
                )

            # Validasi
            _logger.info(f"  Attempting button_validate() on {new_picking.name}...")
            try:
                result = new_picking.with_context(
                    skip_backorder=True,
                    skip_immediate=True,
                    skip_sms=True,
                ).button_validate()
                _logger.info(
                    f"  button_validate() returned: {result} | State: {new_picking.state}"
                )
            except Exception as e:
                _logger.error(f"  button_validate() FAILED: {e}")
                raise

            if new_picking.state != 'done':
                _logger.warning(
                    f"  {new_picking.name} masih {new_picking.state}. "
                    f"Fallback: move._action_done()..."
                )
                try:
                    new_move.with_context(
                        skip_backorder=True,
                        skip_immediate=True,
                    )._action_done()
                    _logger.info(
                        f"  move._action_done() selesai. "
                        f"Move: {new_move.state} | Picking: {new_picking.state}"
                    )
                except Exception as e2:
                    _logger.error(f"  move._action_done() FAILED: {e2}")
                    raise

            _logger.info(
                f"  FINAL: {new_picking.name} state={new_picking.state} | "
                f"move state={new_move.state}"
            )

            if new_picking.state != 'done':
                raise UserError(f"Picking {new_picking.name} gagal divalidasi otomatis.")

        _logger.info(f"=== END action_create_quantity_backorder for {self.name} ===")

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
                
    # SEBELOM SLOC PINDAH KE SCANNER
    # def _sync_packaging_lines(self):
    #     Packaging = self.env['product.packaging.sap']
    #     PickingPackaging = self.env['picking.packaging.line']

    #     # prefetch all moves
    #     all_moves = self.mapped('move_ids').filtered(lambda m: m.product_id)
    #     if not all_moves:
    #         return

    #     all_templates = all_moves.mapped('product_id.product_tmpl_id')

    #     packaging_data = Packaging.search([
    #         ('product_id', 'in', all_templates.ids),
    #         ('company_id', 'in', self.mapped('company_id').ids)
    #     ])

    #     packaging_map = {(p.product_id.id, p.company_id.id): p for p in packaging_data}

    #     create_vals = []

    #     for picking in self:
    #         moves = picking.move_ids.filtered(lambda m: m.product_id)
    #         if not moves:
    #             continue

    #         existing_products = set(picking.product_packaging_ids.mapped('product_id').ids)

    #         origin_picking = self.env['stock.picking'].sudo().search([
    #             ('name', '=', picking.origin),
    #             ('picking_type_id.production_only', '=', True)
    #         ], limit=1)

    #         packaging_type = (
    #             origin_picking.picking_type_id.packaging_type_id
    #             if origin_picking else picking.picking_type_id.packaging_type_id
    #         )

    #         for move in moves:
    #             tmpl_id = move.product_id.product_tmpl_id.id

    #             if tmpl_id in existing_products:
    #                 continue

    #             packaging = packaging_map.get((tmpl_id, picking.company_id.id))
    #             if not packaging:
    #                 continue

    #             create_vals.append({
    #                 'picking_id': picking.id,
    #                 'product_id': tmpl_id,
    #                 'product_uom_desc': packaging.product_uom_desc,
    #                 'packaging_code': packaging.packaging_code,
    #                 'packaging_desc': packaging.packaging_desc,
    #                 'packaging_type_id': packaging_type.id,
    #                 'company_id': picking.company_id.id,
    #                 'move_type_sap': packaging_type.move_type_sap,
    #             })

    #     if create_vals:
    #         PickingPackaging.create(create_vals)

    # def button_validate(self):
    #     res = super().button_validate()
    #     next_pickings = self.mapped('move_ids.move_dest_ids.picking_id').filtered(lambda p: p)
    #     (self | next_pickings)._sync_packaging_lines()
    #     return res