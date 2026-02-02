from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class InheritStockLot(models.Model):
    _inherit = 'stock.lot'

    uom_bag_id = fields.Many2one('uom.uom',  tracking=True)
    bag_qty = fields.Float(string="Bag", tracking=True)
    
    # @api.onchange('product_id', 'product_qty')
    # def onchange_product_qty_kg(self):
    #     for rec in self:
    #         if rec.product_id or rec.product_qty > 0:
    #             rec.uom_bag_id = rec.product_id.uom_bag_id.id or False
    #             rec.bag_qty = rec.product_qty / rec.uom_bag_id.relative_factor
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._prepare_bag_vals(vals)

        records = super().create(vals_list)
        return records

    def write(self, vals):
        if 'product_id' in vals or 'quantity' in vals:
            for rec in self:
                rec._prepare_bag_vals(vals)

        res = super().write(vals)
        return res
    
    def _prepare_bag_vals(self, vals):
        product_id = vals.get('product_id')
        quantity = vals.get('quantity')
        if product_id is None and quantity is None:
            return vals

        if product_id:
            product = self.env['product.product'].sudo().browse(product_id)
        else:
            product = self.product_id

        qty = quantity if quantity is not None else self.quantity
        uom_bag = product.uom_bag_id if product else False
        vals['uom_bag_id'] = uom_bag.id if uom_bag else False

        if uom_bag and uom_bag.relative_factor and qty:
            vals['bag_qty'] = qty / uom_bag.relative_factor
        else:
            vals['bag_qty'] = 0.0

        return vals