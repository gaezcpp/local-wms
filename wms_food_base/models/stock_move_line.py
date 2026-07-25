from odoo import api, models
from odoo.addons.wms_base_warehouse.models.stock_move_line import InheritBaseStockMoveLine as _WbwStockMoveLine
from odoo.addons.wms_inherit_stock_barcode.models.stock_move_line import StockMoveLine as _SbStockMoveLine


class FoodStockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    # wms_base_warehouse is the innermost FEED customization for create/write,
    # so jumping past it also skips wms_inherit_stock_barcode's create/write.

    @api.model_create_multi
    def create(self, vals_list):
        food_vals, other_vals = [], []
        for vals in vals_list:
            company = self.env['res.company'].browse(vals['company_id']) if vals.get('company_id') else self.env.company
            (food_vals if company.wms_type == 'FOOD' else other_vals).append(vals)

        records = self.browse()
        if food_vals:
            records |= super(_WbwStockMoveLine, self).create(food_vals)
        if other_vals:
            records |= super(FoodStockMoveLine, self).create(other_vals)
        return records

    def write(self, vals):
        food = self.filtered(lambda l: l.company_id.wms_type == 'FOOD')
        other = self - food

        res = True
        if food:
            res = super(_WbwStockMoveLine, food).write(vals) and res
        if other:
            res = super(FoodStockMoveLine, other).write(vals) and res
        return res

    def _action_done(self):
        food = self.filtered(lambda l: l.company_id.wms_type == 'FOOD')
        other = self - food

        res = None
        if food:
            res = super(_WbwStockMoveLine, food)._action_done()
        if other:
            res = super(FoodStockMoveLine, other)._action_done()
        return res

    def _synchronize_quant(self, quantity, location, action="available", in_date=False, **quants_value):
        if self.company_id.wms_type == 'FOOD':
            return super(_SbStockMoveLine, self)._synchronize_quant(
                quantity, location, action=action, in_date=in_date, **quants_value
            )
        return super(FoodStockMoveLine, self)._synchronize_quant(
            quantity, location, action=action, in_date=in_date, **quants_value
        )
