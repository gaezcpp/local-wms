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
        # print(f"MOVES UU {moves_uu} | MOVES NORMAL {moves_normal}")
        if moves_normal:
            res = super(StockMove, moves_normal)._action_assign()
        if moves_uu:
            res = super(StockMove, moves_uu.with_context(uu_only=True))._action_assign()
        return res
