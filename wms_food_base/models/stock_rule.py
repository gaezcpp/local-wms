from odoo import models
from odoo.addons.wms_base_warehouse.models.stock_rule import StockRule as _WbwStockRule


class FoodStockRule(models.Model):
    _inherit = 'stock.rule'

    def _get_stock_move_values(self, product_id, product_qty, product_uom, location_id, name, origin, company_id, values):
        company = self.env['res.company'].browse(company_id) if company_id else self.env.company
        if company and company.wms_type == 'FOOD':
            return super(_WbwStockRule, self)._get_stock_move_values(
                product_id, product_qty, product_uom, location_id, name, origin, company_id, values
            )
        return super(FoodStockRule, self)._get_stock_move_values(
            product_id, product_qty, product_uom, location_id, name, origin, company_id, values
        )
