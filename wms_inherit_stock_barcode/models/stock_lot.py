from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class InheritStockLot(models.Model):
    _inherit = 'stock.lot'

    uom_bag_id = fields.Many2one(comodel_name='uom.uom', string="Unit", related='product_id.uom_bag_id')
    bag_qty = fields.Float(string="Pack Qty", compute='_compute_bag_qty', store=True)
    
    @api.depends('product_qty', 'uom_bag_id')
    def _compute_bag_qty(self):
        for record in self:
            if record.uom_bag_id and record.product_uom_id:
                record.bag_qty = record.product_uom_id._compute_quantity(record.product_qty, record.uom_bag_id)
            else:
                record.bag_qty = 0.0
    
    # @api.model_create_multi
    # def create(self, vals_list):
    #     for vals in vals_list:
    #         self._prepare_bag_vals(vals)
    #     records = super().create(vals_list)
    #     return records

    # def write(self, vals):
    #     res = super().write(vals)
    #     if 'quantity' in vals:
    #         for quant in self:
    #             if quant.lot_id:
    #                 quant.lot_id._prepare_bag_vals({'product_qty': quant.lot_id.product_qty})
    #                 lot = quant.lot_id
    #                 product = lot.product_id
    #                 qty = lot.product_qty
    #                 uom_bag = product.uom_bag_id
    #                 product_uom = product.uom_id
    #                 if uom_bag and qty and product_uom:
    #                     lot.bag_qty = product_uom._compute_quantity(qty, uom_bag)
    #                     lot.uom_bag_id = uom_bag.id
    #     return res
    
    # def _prepare_bag_vals(self, vals):
    #     product_id = vals.get('product_id')
    #     quantity = vals.get('product_qty')

    #     if product_id is None and quantity is None:
    #         return vals

    #     if product_id:
    #         product = self.env['product.product'].sudo().browse(product_id)
    #     else:
    #         product = self.product_id

    #     if quantity is None:
    #         quantity = self.product_qty or 0.0

    #     qty = quantity
    #     uom_bag = product.uom_bag_id if product else False
    #     product_uom = product.uom_id if product else False

    #     vals['uom_bag_id'] = uom_bag.id if uom_bag else False

    #     if uom_bag and qty and product_uom:
    #         vals['bag_qty'] = product_uom._compute_quantity(qty, uom_bag)
    #     else:
    #         vals['bag_qty'] = 0.0

    #     return vals