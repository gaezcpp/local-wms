from odoo import models
from odoo.exceptions import UserError


class FoodStockQuant(models.Model):
    _inherit = 'stock.quant'

    def _gather(self, product_id, location_id, lot_id=None, package_id=None,
                owner_id=None, strict=False, **kwargs):
        company = location_id.company_id if location_id else self.env.company
        if company and company.wms_type == 'FOOD':
            raise UserError(
                "FOOD warehouse operations are not yet supported. "
                "Company WMS Type must be FEED or empty."
            )
        return super()._gather(
            product_id, location_id, lot_id=lot_id, package_id=package_id,
            owner_id=owner_id, strict=strict, **kwargs
        )
