from odoo import models
from odoo.exceptions import UserError


class FoodStockPicking(models.Model):
    _inherit = 'stock.picking'

    def _food_check(self):
        for picking in self:
            if picking.company_id.wms_type == 'FOOD':
                raise UserError(
                    "FOOD warehouse operations are not yet supported. "
                    "Company WMS Type must be FEED or empty."
                )

    def action_confirm(self):
        self._food_check()
        return super().action_confirm()

    def button_validate(self):
        self._food_check()
        return super().button_validate()

    def _create_backorder(self):
        self._food_check()
        return super()._create_backorder()
