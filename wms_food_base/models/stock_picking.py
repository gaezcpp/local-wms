from odoo import api, models
from odoo.addons.wms_base_warehouse.models.stock_picking import InheritBaseStockPicking as _WbwStockPicking
from odoo.addons.wms_production_order_sap.models.stock_picking import InheritBaseStockPicking as _PosStockPicking
from odoo.addons.wms_sale_order_sap.models.stock_picking import SaleStockPicking as _SosStockPicking


class FoodStockPicking(models.Model):
    _inherit = 'stock.picking'

    # NOTE: every method below is customized for FEED by one or more of
    # wms_base_warehouse / wms_inherit_stock_barcode / wms_production_order_sap /
    # wms_sale_order_sap. For a FOOD company we jump straight past the
    # innermost (earliest-loaded) of those custom classes via super(), which
    # skips ALL addons_custom layers for that method and lands on native
    # Odoo behavior. For anything else (FEED or empty) we call super()
    # normally so the existing FEED chain runs unchanged.

    def action_confirm(self):
        food = self.filtered(lambda p: p.company_id.wms_type == 'FOOD')
        other = self - food

        res = True
        if food:
            res = super(_PosStockPicking, food).action_confirm() and res
        if other:
            res = super(FoodStockPicking, other).action_confirm() and res
        return res

    def button_validate(self):
        food = self.filtered(lambda p: p.company_id.wms_type == 'FOOD')
        other = self - food

        if food:
            res = super(_WbwStockPicking, food).button_validate()
            if isinstance(res, dict) or not other:
                return res
        if other:
            return super(FoodStockPicking, other).button_validate()
        return True

    def _create_backorder(self, backorder_moves=None):
        food = self.filtered(lambda p: p.company_id.wms_type == 'FOOD')
        other = self - food

        backorders = self.browse()
        if food:
            backorders |= super(_WbwStockPicking, food)._create_backorder(backorder_moves=backorder_moves)
        if other:
            backorders |= super(FoodStockPicking, other)._create_backorder(backorder_moves=backorder_moves)
        return backorders

    def copy(self, default=None):
        if self.company_id.wms_type == 'FOOD':
            return super(_WbwStockPicking, self).copy(default)
        return super(FoodStockPicking, self).copy(default)

    def _action_done(self):
        food = self.filtered(lambda p: p.company_id.wms_type == 'FOOD')
        other = self - food

        res = self.browse()
        if food:
            res |= super(_PosStockPicking, food)._action_done()
        if other:
            res |= super(FoodStockPicking, other)._action_done()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        food_vals, other_vals = [], []
        for vals in vals_list:
            company = self.env['res.company'].browse(vals['company_id']) if vals.get('company_id') else self.env.company
            (food_vals if company.wms_type == 'FOOD' else other_vals).append(vals)

        records = self.browse()
        if food_vals:
            records |= super(_SosStockPicking, self).create(food_vals)
        if other_vals:
            records |= super(FoodStockPicking, self).create(other_vals)
        return records

    def write(self, vals):
        food = self.filtered(lambda p: p.company_id.wms_type == 'FOOD')
        other = self - food

        res = True
        if food:
            res = super(_SosStockPicking, food).write(vals) and res
        if other:
            res = super(FoodStockPicking, other).write(vals) and res
        return res
