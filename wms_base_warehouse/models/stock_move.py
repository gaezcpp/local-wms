from odoo import models, fields, api


class StockMove(models.Model):
    _inherit = 'stock.move'

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
