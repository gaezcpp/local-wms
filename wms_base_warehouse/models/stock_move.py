from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = 'stock.move'
    
    sap_seq = fields.Integer(string="Seq")
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
            
    def _action_assign(self, **kwargs):
        bypass = self.env.context.get('bypass_adjust_demand', False)
        moves_uu = self.filtered(lambda m: m.picking_id.picking_type_id.uu_only)
        # moves_full_pallet = self.filtered(lambda m: m.picking_id.picking_type_id.book_full_pallet)
        # moves_outgoing = self.filtered(lambda m: m.picking_id.picking_type_id.code == 'outgoing')
        moves_full_pallet = self.filtered(
            lambda m: m.picking_id.picking_type_id.book_full_pallet and not bypass
        )
        moves_outgoing = self.filtered(
            lambda m: m.picking_id.picking_type_id.code == 'outgoing' and not bypass
        )
        moves_split_package = self.filtered(lambda m: m.picking_id.picking_type_id.split_package)
        
        moves_to_check_full = moves_uu | moves_full_pallet
        moves_normal = self - moves_to_check_full
        moves_fp_only = moves_full_pallet - moves_uu
        
        res = True
        
        if moves_normal:
            res = super(StockMove, moves_normal)._action_assign(**kwargs) and res
        if moves_uu:
            res = super(StockMove, moves_uu.with_context(uu_only=True))._action_assign(**kwargs) and res
        if moves_fp_only:
            res = super(StockMove, moves_fp_only)._action_assign(**kwargs) and res

        need_reassign = self.env['stock.move'].sudo()
        for move in moves_full_pallet:
            total_actual_pkg_qty = 0
            has_partial = False
            
            for line in move.move_line_ids:
                if line.package_id:
                    actual_pkg_qty = sum(line.package_id.quant_ids.filtered(lambda q: q.product_id == line.product_id).mapped('quantity'))
                    total_actual_pkg_qty += actual_pkg_qty
                    if line.quantity < actual_pkg_qty:
                        has_partial = True
                        
            if has_partial and move.product_uom_qty < total_actual_pkg_qty:
                move.write({'product_uom_qty': total_actual_pkg_qty})
                need_reassign |= move
                dest_moves = move.move_dest_ids
                while dest_moves:
                    valid_dest = dest_moves.filtered(lambda m: m.picking_id.picking_type_id.book_full_pallet)
                    
                    if valid_dest:
                        valid_dest.sudo().write({'product_uom_qty': total_actual_pkg_qty})
                        dest_moves = valid_dest.mapped('move_dest_ids')
                    else:
                        break
                
        if need_reassign:
            need_reassign._do_unreserve()
            need_reassign_uu = need_reassign & moves_uu
            need_reassign_others = need_reassign - moves_uu
            
            if need_reassign_others:
                _logger.info("_action_assign Check Availability need_reassign_others")
                super(StockMove, need_reassign_others)._action_assign()
            if need_reassign_uu:
                _logger.info("_action_assign Check Availability need_reassign_uu")
                super(StockMove, need_reassign_uu.with_context(uu_only=True))._action_assign()

        moves_uu_to_set = moves_uu - moves_split_package
        for line in moves_uu_to_set.move_line_ids:
            if line.package_id and not line.result_package_id:
                _logger.info("Isi Otomatis Destination Package Untuk Scanner")
                line.write({'result_package_id': line.package_id.id})
                
        for move in moves_outgoing:
            _logger.info("Outgoing otomatis Adjust Demand")
            if move.move_orig_ids:
                orig_qty = sum(move.move_orig_ids.mapped('quantity'))
                if orig_qty > 0 and move.product_uom_qty != orig_qty:
                    move.write({
                        'product_uom_qty': orig_qty,
                        'quantity': orig_qty
                    })
            
        moves_to_clear_package = moves_outgoing | moves_split_package
        for move in moves_to_clear_package:
            _logger.info("Menghapus Destination Package (Outgoing / Split Package)")
            lines_to_clear = move.move_line_ids.filtered(lambda l: l.result_package_id)
            if lines_to_clear:
                lines_to_clear.write({'result_package_id': False})
                
        return res
    
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
        res = super()._action_done(**kwargs)
        for move in res:
            for line in move.move_line_ids:
                if line.state == 'done' and line.stock_type:
                    domain = [
                        ('product_id', '=', line.product_id.id),
                        ('location_id', '=', line.location_dest_id.id),
                    ]
                    if line.lot_id:
                        domain.append(('lot_id', '=', line.lot_id.id))
                    if line.result_package_id:
                        domain.append(('package_id', '=', line.result_package_id.id))
                    
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
            }
            
            if not is_production_only and not res.get('stock_type') and matched_line.stock_type:
                update_vals['stock_type'] = matched_line.stock_type
                
            res.update(update_vals)

        return res