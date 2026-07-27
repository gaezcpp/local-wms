from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging
_logger = logging.getLogger(__name__)


class ProductWIP(models.Model):
    _name = 'product.wip'
    _description = 'Product WIP'
    
    parent_product_id = fields.Many2one(comodel_name='product.template', string="Product Temp")
    product_id = fields.Many2one(comodel_name='product.product', string="Product WIP")
    default_code = fields.Char(string="Reference")
    warehouse_id = fields.Many2one(comodel_name='stock.warehouse', string="WH Category")
    
    @api.onchange('product_id')
    def onchange_product_data(self):
        for rec in self:
            product = rec.product_id
            if product:
                rec.default_code = product.default_code
            else:
                rec.default_code = False