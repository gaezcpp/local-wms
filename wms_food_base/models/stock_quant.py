from odoo import api, fields, models
from odoo.addons.wms_base_warehouse.models.stock_quant import StockQuant as _WbwStockQuant
from odoo.addons.wms_inherit_stock_barcode.models.stock_quant import InheritStockQuant as _SbStockQuant


class FoodStockQuant(models.Model):
    _inherit = 'stock.quant'

    # Related, non-stored: lets the views below decide per-record whether to
    # show the FEED-customized arch or the plain Odoo one.
    wms_type = fields.Selection(related='company_id.wms_type', string="WMS Type", store=True, index=True)

    @api.model
    def _gather(self, product_id, location_id, lot_id=None, package_id=None, owner_id=None, strict=False, qty=None):
        company = location_id.company_id if location_id else self.env.company
        if company and company.wms_type == 'FOOD':
            return super(_WbwStockQuant, self)._gather(
                product_id, location_id, lot_id=lot_id, package_id=package_id,
                owner_id=owner_id, strict=strict, qty=qty
            )
        return super(FoodStockQuant, self)._gather(
            product_id, location_id, lot_id=lot_id, package_id=package_id,
            owner_id=owner_id, strict=strict, qty=qty
        )

    # wms_base_warehouse is the innermost FEED customization for write, so
    # jumping past it also skips wms_inherit_stock_barcode's write. create is
    # only customized by wms_inherit_stock_barcode.
    @api.model_create_multi
    def create(self, vals_list):
        food_vals, other_vals = [], []
        for vals in vals_list:
            company = self.env['res.company'].browse(vals['company_id']) if vals.get('company_id') else self.env.company
            (food_vals if company.wms_type == 'FOOD' else other_vals).append(vals)

        records = self.browse()
        if food_vals:
            records |= super(_SbStockQuant, self).create(food_vals)
        if other_vals:
            records |= super(FoodStockQuant, self).create(other_vals)
        return records

    def write(self, vals):
        food = self.filtered(lambda q: q.company_id.wms_type == 'FOOD')
        other = self - food

        res = True
        if food:
            res = super(_WbwStockQuant, food).write(vals) and res
        if other:
            res = super(FoodStockQuant, other).write(vals) and res
        return res
