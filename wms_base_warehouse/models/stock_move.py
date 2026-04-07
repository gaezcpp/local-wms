from odoo import models, fields, api


class StockMove(models.Model):
    _inherit = 'stock.move'
    
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

            over = False
            for m in picking.move_ids:
                if m.quantity != m.product_uom_qty:
                    over = True
                    break

            picking.over_delivery = over

    def _action_assign(self):
        moves_uu = self.filtered(lambda m: m.picking_id.picking_type_id.uu_only)
        moves_normal = self - moves_uu
        res = True
        if moves_normal:
            res = super(StockMove, moves_normal)._action_assign()
        if moves_uu:
            res = super(StockMove, moves_uu.with_context(uu_only=True))._action_assign()
        return res
                    
    # ini untuk next transfer
    def _get_new_picking_values(self):
        vals = super()._get_new_picking_values()

        pickings = self.mapped('picking_id').filtered(lambda p: p)
        if pickings:
            picking = pickings[0]
            vals.update({
                'po_sap_id': picking.po_sap_id.id,
                'production_shift_id': picking.production_shift_id.id,
            })

        return vals
    
    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        res = super()._prepare_move_line_vals(quantity=quantity, reserved_quant=reserved_quant)
        if not self.move_orig_ids:
            return res

        origin_lines = self.move_orig_ids.mapped('move_line_ids').sorted('id')
        matched_line = False

        if reserved_quant:
            if reserved_quant.package_id:
                matched_line = origin_lines.filtered(
                    lambda l:
                        l.package_history_id.id == reserved_quant.package_id.id and
                        l.product_id == self.product_id
                )[:1]

            if not matched_line and reserved_quant.package_id:
                matched_line = origin_lines.filtered(
                    lambda l:
                        l.result_package_id.id == reserved_quant.package_id.id and
                        l.product_id == self.product_id
                )[:1]

            if not matched_line and reserved_quant.lot_id:
                matched_line = origin_lines.filtered(
                    lambda l:
                        l.lot_id.id == reserved_quant.lot_id.id and
                        l.product_id == self.product_id
                )[:1]

        if not matched_line:
            matched_line = origin_lines.filtered(
                lambda l: l.product_id == self.product_id
            )[:1]

        if not matched_line and origin_lines:
            matched_line = origin_lines[:1]

        if matched_line:
            res.update({
                'production_line_id': matched_line.production_line_id.id,
                'first_count': matched_line.first_count,
                'last_count': matched_line.last_count,
                'detail_text': matched_line.detail_text,
                'qty_packaging_sap': matched_line.qty_packaging_sap,
            })

        return res