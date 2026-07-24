from odoo import models
from odoo.exceptions import UserError


class FoodStockMove(models.Model):
    _inherit = 'stock.move'

    def _action_assign(self):
        for move in self:
            if move.company_id.wms_type == 'FOOD':
                raise UserError(
                    "FOOD warehouse operations are not yet supported. "
                    "Company WMS Type must be FEED or empty."
                )
        return super()._action_assign()

    def _prepare_move_line_vals(self, quantity=None, reserved_qty=None):
        if self.company_id.wms_type == 'FOOD':
            raise UserError(
                "FOOD warehouse operations are not yet supported. "
                "Company WMS Type must be FEED or empty."
            )
        return super()._prepare_move_line_vals(
            quantity=quantity, reserved_qty=reserved_qty
        )
