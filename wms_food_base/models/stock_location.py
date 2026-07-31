from odoo import fields, models
from odoo.addons.wms_base_warehouse.models.stock_location import InheritStockLocation as _WbwStockLocation


class FoodStockLocation(models.Model):
    _inherit = 'stock.location'

    # Related, non-stored: lets the views below decide per-record whether to
    # show the FEED-customized arch or the plain Odoo one.
    wms_type = fields.Selection(related='company_id.wms_type', string="WMS Type", store=True, index=True)

    def write(self, vals):
        food = self.filtered(lambda l: l.company_id.wms_type == 'FOOD')
        other = self - food

        res = True
        if food:
            res = super(_WbwStockLocation, food).write(vals) and res
        if other:
            res = super(FoodStockLocation, other).write(vals) and res
        return res

    def _get_putaway_strategy(self, product, quantity=0, package=None, packaging=None, additional_qty=None):
        company = self.company_id if self.company_id else self.env.company
        if company and company.wms_type == 'FOOD':
            return super(_WbwStockLocation, self)._get_putaway_strategy(
                product, quantity=quantity, package=package, packaging=packaging, additional_qty=additional_qty
            )
        return super(FoodStockLocation, self)._get_putaway_strategy(
            product, quantity=quantity, package=package, packaging=packaging, additional_qty=additional_qty
        )
