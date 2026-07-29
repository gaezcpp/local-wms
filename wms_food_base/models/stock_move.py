from odoo import api, fields, models
from odoo.addons.wms_base_warehouse.models.stock_move import StockMove as _WbwStockMove


class FoodStockMove(models.Model):
    _inherit = 'stock.move'

    # Related, non-stored: lets the views below decide per-record whether to
    # show the FEED-customized arch or the plain Odoo one.
    wms_type = fields.Selection(related='picking_id.wms_type', string="WMS Type", store=True, index=True)

    # See stock_picking.py for the rationale behind the super()-jump pattern.
    # wms_base_warehouse is the innermost (earliest-loaded) FEED customization
    # for stock.move, so jumping past it also skips wms_inherit_stock_barcode's
    # (more outer, log-only) create override.

    @api.model_create_multi
    def create(self, vals_list):
        food_vals, other_vals = [], []
        for vals in vals_list:
            company = self.env['res.company'].browse(vals['company_id']) if vals.get('company_id') else self.env.company
            (food_vals if company.wms_type == 'FOOD' else other_vals).append(vals)

        moves = self.browse()
        if food_vals:
            moves |= super(_WbwStockMove, self).create(food_vals)
        if other_vals:
            moves |= super(FoodStockMove, self).create(other_vals)
        return moves

    def write(self, vals):
        food = self.filtered(lambda m: m.company_id.wms_type == 'FOOD')
        other = self - food

        res = True
        if food:
            res = super(_WbwStockMove, food).write(vals) and res
        if other:
            res = super(FoodStockMove, other).write(vals) and res
        return res

    def _action_assign(self, **kwargs):
        food = self.filtered(lambda m: m.company_id.wms_type == 'FOOD')
        other = self - food

        res = True
        if food:
            res = super(_WbwStockMove, food)._action_assign(**kwargs) and res
        if other:
            res = super(FoodStockMove, other)._action_assign(**kwargs) and res
        return res

    def _get_new_picking_values(self):
        if self and self[0].company_id.wms_type == 'FOOD':
            return super(_WbwStockMove, self)._get_new_picking_values()
        return super(FoodStockMove, self)._get_new_picking_values()

    def _prepare_procurement_values(self):
        self.ensure_one()
        if self.company_id.wms_type == 'FOOD':
            return super(_WbwStockMove, self)._prepare_procurement_values()
        return super(FoodStockMove, self)._prepare_procurement_values()

    def _action_done(self, **kwargs):
        food = self.filtered(lambda m: m.company_id.wms_type == 'FOOD')
        other = self - food

        res = self.browse()
        if food:
            res |= super(_WbwStockMove, food)._action_done(**kwargs)
        if other:
            res |= super(FoodStockMove, other)._action_done(**kwargs)
        return res

    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        self.ensure_one()
        if self.company_id.wms_type == 'FOOD':
            return super(_WbwStockMove, self)._prepare_move_line_vals(quantity=quantity, reserved_quant=reserved_quant)
        return super(FoodStockMove, self)._prepare_move_line_vals(quantity=quantity, reserved_quant=reserved_quant)
