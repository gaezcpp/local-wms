from odoo import models, fields, api
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare
import logging
_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = 'stock.move'
    
    sap_seq = fields.Integer(string="Seq", index=True)
    order_seq = fields.Integer(string="Order Seq")
    
    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        moves._update_over_delivery()
        return moves

    def write(self, vals):
        res = super().write(vals)
        if any(field in vals for field in ['quantity', 'product_uom_qty']):
            self._update_over_delivery()
        return res
    
    def _update_over_delivery(self):
        for move in self:
            picking = move.picking_id
            if not picking:
                continue
            over = any(m.quantity != m.product_uom_qty for m in picking.move_ids)
            picking.over_delivery = over
    
    def _get_package_actual_qty(self, line):
        quants = line.package_id.quant_ids.filtered(lambda q: q.product_id == line.product_id)
        if line.lot_id:
            quants = quants.filtered(lambda q: q.lot_id == line.lot_id)
        return sum(quants.mapped('quantity'))

    def _get_pkg_reserved_qty_elsewhere(self, line):
        domain = [
            ('package_id', '=', line.package_id.id),
            ('product_id', '=', line.product_id.id),
            ('id', '!=', line.id),
            ('state', 'not in', ['done', 'cancel']),
        ]
        if line.lot_id:
            domain.append(('lot_id', '=', line.lot_id.id))
        return sum(self.env['stock.move.line'].sudo().search(domain).mapped('quantity'))

    def _force_full_pallet_line(self, line, actual_pkg_qty=None):
        rounding = line.product_id.uom_id.rounding
        if actual_pkg_qty is None:
            actual_pkg_qty = self._get_package_actual_qty(line)
        if float_compare(line.quantity, actual_pkg_qty, precision_rounding=rounding) >= 0:
            return False

        reserved_elsewhere = self._get_pkg_reserved_qty_elsewhere(line)
        available_for_line = actual_pkg_qty - reserved_elsewhere

        if float_compare(available_for_line, line.quantity, precision_rounding=rounding) <= 0:
            _logger.warning(
                f"[GRGI] full_pallet_line BLOCKED pkg={line.package_id.display_name} "
                f"reserved_elsewhere={reserved_elsewhere} actual={actual_pkg_qty} line={line.id}"
            )
            return True

        target_qty = min(available_for_line, actual_pkg_qty)
        _logger.info(
            f"[GRGI] full_pallet_line line={line.id} picking={line.move_id.picking_id.name} "
            f"qty {line.quantity}->{target_qty} actual_pkg={actual_pkg_qty}"
        )
        line.sudo().write({'quantity': target_qty})
        return float_compare(target_qty, actual_pkg_qty, precision_rounding=rounding) < 0

    def _force_full_pallet_dest_moves(self, move):
        need_reassign = self.env['stock.move'].sudo()
        dest_moves = move.move_dest_ids.filtered(lambda m: m.picking_id.picking_type_id.book_full_pallet)
        while dest_moves:
            for dest_move in dest_moves:
                for line in dest_move.move_line_ids.filtered('package_id'):
                    if self._force_full_pallet_line(line):
                        need_reassign |= dest_move
            dest_moves = dest_moves.move_dest_ids.filtered(lambda m: m.picking_id.picking_type_id.book_full_pallet)
        return need_reassign

    def _book_full_pallet(self, moves_full_pallet, moves_uu):
        need_reassign = self.env['stock.move'].sudo()

        for move in moves_full_pallet:
            lines = move.move_line_ids.filtered('package_id')
            if not lines:
                continue

            rounding = move.product_id.uom_id.rounding
            actual_qty_by_line = {line: self._get_package_actual_qty(line) for line in lines}
            total_actual_qty = sum(actual_qty_by_line.values())
            has_partial = any(
                float_compare(line.quantity, actual_qty_by_line[line], precision_rounding=rounding) < 0
                for line in lines
            )

            if not has_partial or float_compare(move.quantity, total_actual_qty, precision_rounding=rounding) >= 0:
                continue

            for line in lines:
                if self._force_full_pallet_line(line, actual_qty_by_line[line]):
                    need_reassign |= move

            need_reassign |= self._force_full_pallet_dest_moves(move)

        if need_reassign:
            need_reassign._do_unreserve()
            need_reassign_uu = need_reassign & moves_uu
            need_reassign_others = need_reassign - moves_uu

            if need_reassign_others:
                super(StockMove, need_reassign_others)._action_assign()
            if need_reassign_uu:
                super(StockMove, need_reassign_uu.with_context(uu_only=True))._action_assign()

    def _autofill_result_package(self, moves):
        for line in moves.move_line_ids.filtered(lambda l: l.package_id and not l.result_package_id):
            line.write({'result_package_id': line.package_id.id})

    def _clear_result_package(self, moves):
        lines = moves.move_line_ids.filtered('result_package_id')
        if lines:
            lines.write({'result_package_id': False})
            
    def _consolidate_sml_per_quant(self):
        for picking in self.mapped('picking_id'):
            sml_by_quant = {}
            lines_to_unlink = self.env['stock.move.line'].sudo()
            
            for line in picking.move_line_ids.filtered(lambda l: l.state not in ['done', 'cancel']):
                quant_key = (
                    line.location_id.id, 
                    line.lot_id.id, 
                    line.package_id.id, 
                    line.owner_id.id
                )
                
                if quant_key not in sml_by_quant:
                    sml_by_quant[quant_key] = line
                else:
                    first_line = sml_by_quant[quant_key]
                    first_line.sudo().write({
                        'quantity': first_line.quantity + line.quantity
                    })
                    lines_to_unlink |= line
            
            if lines_to_unlink:
                lines_to_unlink.unlink()

    ## NOTE INI BELUM DITES DI QAS, TAPI NAIKIN AJA
    def _action_assign(self, **kwargs):
        bypass = self.env.context.get('bypass_adjust_demand', False)
        moves_uu = self.filtered(lambda m: m.picking_id.picking_type_id.uu_only)
        moves_full_pallet = self.filtered(lambda m: m.picking_id.picking_type_id.book_full_pallet and not bypass)
        moves_split_package = self.filtered(lambda m: m.picking_id.picking_type_id.split_package)

        moves_normal = self - moves_uu - moves_full_pallet
        moves_fp_only = moves_full_pallet - moves_uu

        res = True
        if moves_normal:
            res = super(StockMove, moves_normal)._action_assign(**kwargs) and res
        if moves_uu:
            res = super(StockMove, moves_uu.with_context(uu_only=True))._action_assign(**kwargs) and res
        if moves_fp_only:
            res = super(StockMove, moves_fp_only)._action_assign(**kwargs) and res
            
        self._consolidate_sml_per_quant()

        if moves_full_pallet:
            self._book_full_pallet(moves_full_pallet, moves_uu)

        moves_uu_to_set = moves_uu - moves_split_package
        if moves_uu_to_set:
            self._autofill_result_package(moves_uu_to_set)

        if moves_split_package:
            self._clear_result_package(moves_split_package)

        return res
    
    # NOTE INI MASIH ADA YANG DOUBLE RESERVE QUANT YANG SAMA
    # def _get_pkg_reserved_qty_elsewhere(self, line):
    #     """Qty dari package/product `line` yang sudah direserve oleh move line
    #     LAIN (move/picking berbeda) yang belum done/cancel. Dipakai supaya
    #     force-bump full-pallet tidak menulis reserved_quantity melebihi
    #     quantity on-hand saat package yang sama dipakai lebih dari satu
    #     move/picking sekaligus."""
    #     domain = [
    #         ('package_id', '=', line.package_id.id),
    #         ('product_id', '=', line.product_id.id),
    #         ('id', '!=', line.id),
    #         ('state', 'not in', ['done', 'cancel']),
    #     ]
    #     return sum(self.env['stock.move.line'].sudo().search(domain).mapped('quantity'))

    # def _force_full_pallet_line(self, line):
    #     """Bump `line.quantity` ke qty fisik pallet, dibatasi oleh qty yang
    #     belum direserve move/picking lain untuk package yang sama.
    #     Return True kalau bump tidak bisa mencapai full qty pallet karena
    #     package sedang dipakai (contended) -- caller harus re-assign move
    #     ini lewat jalur normal Odoo supaya cari quant/package lain."""
    #     actual_pkg_qty = sum(line.package_id.quant_ids.filtered(
    #         lambda q: q.product_id == line.product_id).mapped('quantity'))
    #     if line.quantity >= actual_pkg_qty:
    #         return False

    #     reserved_elsewhere = self._get_pkg_reserved_qty_elsewhere(line)
    #     available_for_line = actual_pkg_qty - reserved_elsewhere

    #     if available_for_line <= line.quantity:
    #         _logger.warning(
    #             f"[GRGI] full_pallet_line BLOCKED pkg={line.package_id.display_name} "
    #             f"reserved_elsewhere={reserved_elsewhere} actual={actual_pkg_qty} line={line.id}"
    #         )
    #         return True

    #     target_qty = min(available_for_line, actual_pkg_qty)
    #     _logger.info(
    #         f"[GRGI] full_pallet_line line={line.id} picking={line.move_id.picking_id.name} "
    #         f"qty {line.quantity}->{target_qty} actual_pkg={actual_pkg_qty}"
    #     )
    #     line.sudo().write({'quantity': target_qty})
    #     return target_qty < actual_pkg_qty

    # def _action_assign(self, **kwargs):
    #     for move in self:
    #         _logger.info(
    #             f"[GRGI] _action_assign IN move={move.id} picking={move.picking_id.name} "
    #             f"type={move.picking_id.picking_type_id.name} product={move.product_id.default_code} "
    #             f"demand={move.product_uom_qty} qty={move.quantity} state={move.state}"
    #         )

    #     bypass = self.env.context.get('bypass_adjust_demand', False)
    #     moves_uu = self.filtered(lambda m: m.picking_id.picking_type_id.uu_only)
    #     moves_full_pallet = self.filtered(lambda m: m.picking_id.picking_type_id.book_full_pallet and not bypass)
    #     # moves_outgoing = self.filtered(lambda m: m.picking_id.picking_type_id.code == 'outgoing' and not bypass)
    #     moves_split_package = self.filtered(lambda m: m.picking_id.picking_type_id.split_package)

    #     moves_to_check_full = moves_uu | moves_full_pallet
    #     moves_normal = self - moves_to_check_full
    #     moves_fp_only = moves_full_pallet - moves_uu

    #     res = True

    #     if moves_normal:
    #         res = super(StockMove, moves_normal)._action_assign(**kwargs) and res
    #     if moves_uu:
    #         res = super(StockMove, moves_uu.with_context(uu_only=True))._action_assign(**kwargs) and res
    #     if moves_fp_only:
    #         res = super(StockMove, moves_fp_only)._action_assign(**kwargs) and res

    #     need_reassign = self.env['stock.move'].sudo()
    #     for move in moves_full_pallet:
    #         total_actual_pkg_qty = 0
    #         has_partial = False

    #         for line in move.move_line_ids:
    #             if line.package_id:
    #                 actual_pkg_qty = sum(line.package_id.quant_ids.filtered(lambda q: q.product_id == line.product_id).mapped('quantity'))
    #                 total_actual_pkg_qty += actual_pkg_qty
    #                 # _logger.info(f"ACTUAL PKG QTY {actual_pkg_qty} TOTAL ACTUAL PKG QTY {total_actual_pkg_qty}")
    #                 if line.quantity < actual_pkg_qty:
    #                     has_partial = True

    #         if has_partial and move.quantity < total_actual_pkg_qty:
    #             # _logger.info("MASUK SINI HAS PARTIAL")
    #             for line in move.move_line_ids.filtered(lambda l: l.package_id):
    #                 if self._force_full_pallet_line(line):
    #                     need_reassign |= move

    #             dest_moves = move.move_dest_ids
    #             while dest_moves:
    #                 valid_dest = dest_moves.filtered(lambda m: m.picking_id.picking_type_id.book_full_pallet)
    #                 if valid_dest:
    #                     for dest_move in valid_dest:
    #                         for dline in dest_move.move_line_ids.filtered(lambda l: l.package_id):
    #                             if self._force_full_pallet_line(dline):
    #                                 need_reassign |= dest_move
    #                     dest_moves = valid_dest.mapped('move_dest_ids')
    #                 else:
    #                     break

    #     if need_reassign:
    #         need_reassign._do_unreserve()
    #         need_reassign_uu = need_reassign & moves_uu
    #         need_reassign_others = need_reassign - moves_uu

    #         if need_reassign_others:
    #             # _logger.info("_action_assign Check Availability need_reassign_others")
    #             super(StockMove, need_reassign_others)._action_assign()
    #         if need_reassign_uu:
    #             # _logger.info("_action_assign Check Availability need_reassign_uu")
    #             super(StockMove, need_reassign_uu.with_context(uu_only=True))._action_assign()

    #     moves_uu_to_set = moves_uu - moves_split_package
    #     for line in moves_uu_to_set.move_line_ids:
    #         if line.package_id and not line.result_package_id:
    #             # _logger.info("Isi Otomatis Destination Package Untuk Scanner")
    #             line.write({'result_package_id': line.package_id.id})

    #     # for move in moves_outgoing:
    #     #     _logger.info("Outgoing otomatis Adjust Demand")
    #     #     if move.move_orig_ids:
    #     #         orig_qty = sum(move.move_orig_ids.mapped('quantity'))
    #     #         if orig_qty > 0 and move.product_uom_qty != orig_qty:
    #     #             move.write({
    #     #                 'product_uom_qty': orig_qty,
    #     #                 'quantity': orig_qty
    #     #             })

    #     # moves_to_clear_package = moves_outgoing | moves_split_package
    #     moves_to_clear_package = moves_split_package
    #     for move in moves_to_clear_package:
    #         # _logger.info("Menghapus Destination Package (Outgoing / Split Package)")
    #         lines_to_clear = move.move_line_ids.filtered(lambda l: l.result_package_id)
    #         if lines_to_clear:
    #             lines_to_clear.write({'result_package_id': False})

    #     for move in self:
    #         lines = [(l.id, l.quantity, l.lot_id.name) for l in move.move_line_ids]
    #         _logger.info(
    #             f"[GRGI] _action_assign OUT move={move.id} picking={move.picking_id.name} "
    #             f"demand={move.product_uom_qty} qty={move.quantity} state={move.state} lines={lines}"
    #         )

    #     return res
    
    # def _action_assign(self, **kwargs):
    #     bypass = self.env.context.get('bypass_adjust_demand', False)
    #     moves_uu = self.filtered(lambda m: m.picking_id.picking_type_id.uu_only)
    #     moves_full_pallet = self.filtered(lambda m: m.picking_id.picking_type_id.book_full_pallet and not bypass)
    #     moves_outgoing = self.filtered(lambda m: m.picking_id.picking_type_id.code == 'outgoing' and not bypass)
    #     moves_split_package = self.filtered(lambda m: m.picking_id.picking_type_id.split_package)

    #     moves_to_check_full = moves_uu | moves_full_pallet
    #     moves_normal = self - moves_to_check_full
    #     moves_fp_only = moves_full_pallet - moves_uu

    #     res = True

    #     if moves_normal:
    #         res = super(StockMove, moves_normal)._action_assign(**kwargs) and res
    #     if moves_uu:
    #         res = super(StockMove, moves_uu.with_context(uu_only=True))._action_assign(**kwargs) and res
    #     if moves_fp_only:
    #         res = super(StockMove, moves_fp_only)._action_assign(**kwargs) and res

    #     def _package_actual_qty(package, product, lot):
    #         """Qty of `product` (+ `lot` if set) actually inside `package`.
    #         Filtering by lot as well as product avoids double-counting when a
    #         single package holds multiple lots of the same product."""
    #         domain_quants = package.quant_ids.filtered(lambda q: q.product_id == product)
    #         if lot:
    #             domain_quants = domain_quants.filtered(lambda q: q.lot_id == lot)
    #         return sum(domain_quants.mapped('quantity'))

    #     need_reassign = self.env['stock.move'].sudo()

    #     for move in moves_full_pallet:
    #         has_partial = False

    #         # Group move lines by (package, product, lot) so each physical
    #         # package/lot combination is only counted once.
    #         seen_keys = {}
    #         for line in move.move_line_ids.filtered(lambda l: l.package_id):
    #             key = (line.package_id.id, line.product_id.id, line.lot_id.id if line.lot_id else False)
    #             actual_pkg_qty = _package_actual_qty(line.package_id, line.product_id, line.lot_id)
    #             seen_keys[key] = actual_pkg_qty
    #             _logger.info(f"ACTUAL PKG QTY {actual_pkg_qty} for key {key}")
    #             if line.quantity < actual_pkg_qty:
    #                 has_partial = True

    #         total_actual_pkg_qty = sum(seen_keys.values())

    #         if has_partial and move.quantity < total_actual_pkg_qty:
    #             _logger.info("MASUK SINI HAS PARTIAL")
    #             for line in move.move_line_ids.filtered(lambda l: l.package_id):
    #                 actual_pkg_qty = _package_actual_qty(line.package_id, line.product_id, line.lot_id)
    #                 if line.quantity < actual_pkg_qty:
    #                     line.write({'quantity': actual_pkg_qty})

    #             # This move's reservation is now stale relative to the demand
    #             # adjustment above, so it needs to be unreserved and re-assigned.
    #             need_reassign |= move

    #             dest_moves = move.move_dest_ids
    #             while dest_moves:
    #                 valid_dest = dest_moves.filtered(lambda m: m.picking_id.picking_type_id.book_full_pallet)
    #                 if valid_dest:
    #                     for dest_move in valid_dest:
    #                         dest_has_partial = False
    #                         for dline in dest_move.move_line_ids.filtered(lambda l: l.package_id):
    #                             d_actual = _package_actual_qty(dline.package_id, dline.product_id, dline.lot_id)
    #                             if dline.quantity < d_actual:
    #                                 dline.sudo().write({'quantity': d_actual})
    #                                 dest_has_partial = True
    #                         if dest_has_partial:
    #                             need_reassign |= dest_move
    #                     dest_moves = valid_dest.mapped('move_dest_ids')
    #                 else:
    #                     break

    #     if need_reassign:
    #         need_reassign._do_unreserve()
    #         need_reassign_uu = need_reassign & moves_uu
    #         need_reassign_others = need_reassign - moves_uu

    #         if need_reassign_others:
    #             _logger.info("_action_assign Check Availability need_reassign_others")
    #             super(StockMove, need_reassign_others)._action_assign()
    #         if need_reassign_uu:
    #             _logger.info("_action_assign Check Availability need_reassign_uu")
    #             super(StockMove, need_reassign_uu.with_context(uu_only=True))._action_assign()

    #     moves_uu_to_set = moves_uu - moves_split_package
    #     for line in moves_uu_to_set.move_line_ids:
    #         if line.package_id and not line.result_package_id:
    #             _logger.info("Isi Otomatis Destination Package Untuk Scanner")
    #             line.write({'result_package_id': line.package_id.id})

    #     for move in moves_outgoing:
    #         _logger.info("Outgoing otomatis Adjust Demand")
    #         if move.move_orig_ids:
    #             orig_lines = move.move_orig_ids.mapped('move_line_ids')
    #             orig_qty = sum(orig_lines.mapped('quantity'))

    #             if orig_qty > 0 and move.product_uom_qty != orig_qty:
    #                 move.write({
    #                     'product_uom_qty': orig_qty,
    #                     'quantity': orig_qty
    #                 })

    #                 # Hitung ulang demand PER LOT dari origin, bukan hanya total.
    #                 lot_qty_map = {}
    #                 for oline in orig_lines:
    #                     key = oline.lot_id.id if oline.lot_id else False
    #                     lot_qty_map[key] = lot_qty_map.get(key, 0) + oline.quantity

    #                 # Jika ada lebih dari satu lot terlibat, komposisi lot pada
    #                 # origin harus dipertahankan -- jangan biarkan removal strategy
    #                 # bebas memilih lot saat re-assign.
    #                 if len(lot_qty_map) > 1:
    #                     move._do_unreserve()
    #                     existing_lines = move.move_line_ids
    #                     for lot_id, qty in lot_qty_map.items():
    #                         matched_line = existing_lines.filtered(
    #                             lambda l: (l.lot_id.id if l.lot_id else False) == lot_id
    #                         )[:1]
    #                         if matched_line:
    #                             matched_line.write({'quantity': qty})
    #                         else:
    #                             move.write({'move_line_ids': [(0, 0, {
    #                                 'product_id': move.product_id.id,
    #                                 'product_uom_id': move.product_uom.id,
    #                                 'location_id': move.location_id.id,
    #                                 'location_dest_id': move.location_dest_id.id,
    #                                 'lot_id': lot_id or False,
    #                                 'quantity': qty,
    #                             })]})

    #     moves_to_clear_package = moves_outgoing | moves_split_package
    #     for move in moves_to_clear_package:
    #         _logger.info("Menghapus Destination Package (Outgoing / Split Package)")
    #         lines_to_clear = move.move_line_ids.filtered(lambda l: l.result_package_id)
    #         if lines_to_clear:
    #             lines_to_clear.write({'result_package_id': False})

    #     return res
    
    def _get_new_picking_values(self):
        vals = super()._get_new_picking_values()

        if self:
            first_move = self[0]
            picking = first_move.picking_id
            if picking:
                vals.update({
                    'po_sap_id': picking.po_sap_id.id,
                    'production_shift_id': picking.production_shift_id.id,
                })
                
            if first_move.sale_line_id and first_move.sale_line_id.order_id:
                vals['sloc_to'] = first_move.sale_line_id.order_id.sloc_to

        return vals
    
    def _prepare_procurement_values(self):
        self.ensure_one()
        values = super(StockMove, self)._prepare_procurement_values()
        
        if self.sap_seq:
            values['sap_sequence'] = self.sap_seq
        elif self.sale_line_id:
            values['sap_sequence'] = self.sale_line_id.sap_sequence
        elif self.purchase_line_id:
            values['sap_sequence'] = self.purchase_line_id.sap_sequence
            
        if self.order_seq:
            values['order_seq'] = self.order_seq
        elif self.sale_line_id:
            values['order_seq'] = self.sale_line_id.order_seq
        elif self.purchase_line_id:
            values['order_seq'] = self.purchase_line_id.order_seq
            
        return values
    
    def _is_gr_prod(self, vals=None):
        picking = False
        prod_in_move_type = self.env['ir.config_parameter'].sudo().get_param('prod_in_move_type')
        
        if not prod_in_move_type:
            raise ValidationError("prod_in_move_type pada Operation Type belum disetting!")
            
        if vals and vals.get('picking_id'):
            picking = self.env['stock.picking'].browse(vals['picking_id'])
        elif self:
            picking = self[0].picking_id
            
        return picking and picking.picking_type_id.move_type_sap == str(prod_in_move_type)
    
    def _action_done(self, **kwargs):
        for move in self:
            lines = [(l.id, l.quantity, l.lot_id.name, l.location_dest_id.complete_name) for l in move.move_line_ids]
            _logger.info(
                f"[GRGI] _action_done IN move={move.id} picking={move.picking_id.name} "
                f"type={move.picking_id.picking_type_id.name} product={move.product_id.default_code} "
                f"demand={move.product_uom_qty} qty={move.quantity} lines={lines}"
            )

        res = super()._action_done(**kwargs)
        for move in res:
            for line in move.move_line_ids:
                if line.state == 'done' and line.stock_type:
                    domain = [
                        ('product_id', '=', line.product_id.id),
                        ('location_id', '=', line.location_dest_id.id),
                        ('package_id', '=', line.result_package_id.id if line.result_package_id else False), #AI
                    ]
                    if line.lot_id:
                        domain.append(('lot_id', '=', line.lot_id.id))

                    quants = self.env['stock.quant'].search(domain)
                    if quants:
                        quants.sudo().write({'stock_type': line.stock_type})

        return res
    
    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        self.ensure_one()
        res = super()._prepare_move_line_vals(quantity=quantity, reserved_quant=reserved_quant)
        
        is_production_only = self._is_gr_prod()
        
        if is_production_only:
            res['stock_type'] = 'QI'
        elif reserved_quant and reserved_quant.stock_type:
            res['stock_type'] = reserved_quant.stock_type

        if not self.move_orig_ids:
            return res

        origin_lines = self.move_orig_ids.mapped('move_line_ids').sorted('id')
        matched_line = False

        if reserved_quant:
            if reserved_quant.package_id:
                matched_line = origin_lines.filtered(
                    lambda l: l.package_history_id.id == reserved_quant.package_id.id and l.product_id == self.product_id
                )[:1]

            if not matched_line and reserved_quant.package_id:
                matched_line = origin_lines.filtered(
                    lambda l: l.result_package_id.id == reserved_quant.package_id.id and l.product_id == self.product_id
                )[:1]

            if not matched_line and reserved_quant.lot_id:
                matched_line = origin_lines.filtered(
                    lambda l: l.lot_id.id == reserved_quant.lot_id.id and l.product_id == self.product_id
                )[:1]

        if not matched_line:
            matched_line = origin_lines.filtered(
                lambda l: l.product_id == self.product_id
            )[:1]

        if not matched_line and origin_lines:
            matched_line = origin_lines[:1]

        if matched_line:
            update_vals = {
                'production_line_id': matched_line.production_line_id.id,
                'first_count': matched_line.first_count,
                'last_count': matched_line.last_count,
                'detail_text': matched_line.detail_text,
                'qty_packaging_sap': matched_line.qty_packaging_sap,
                'wh_category_id': matched_line.wh_category_id.id if matched_line.wh_category_id else False,
                'pallet_ke': matched_line.pallet_ke,
            }
            
            if not is_production_only and not res.get('stock_type') and matched_line.stock_type:
                update_vals['stock_type'] = matched_line.stock_type
                
            res.update(update_vals)

        return res