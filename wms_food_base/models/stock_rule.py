from odoo import models
from odoo.addons.wms_base_warehouse.models.stock_rule import StockRule as _WbwStockRule


class FoodStockRule(models.Model):
    _inherit = 'stock.rule'

    def _get_stock_move_values(self, product_id, product_qty, product_uom, location_id, name, origin, company_id, values):
        company = company_id or self.env.company
        if company and getattr(company, 'wms_type', False) == 'FOOD':
            return super(_WbwStockRule, self)._get_stock_move_values(
                product_id, product_qty, product_uom, location_id, name, origin, company_id, values
            )
        return super(FoodStockRule, self)._get_stock_move_values(
            product_id, product_qty, product_uom, location_id, name, origin, company_id, values
        )
