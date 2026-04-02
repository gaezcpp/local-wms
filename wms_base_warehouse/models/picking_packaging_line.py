from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging
_logger = logging.getLogger(__name__)


class PickingPackagingLine(models.Model):
    _name = 'picking.packaging.line'
    _description = 'Picking Packaging Line'
    
    picking_id = fields.Many2one(comodel_name='stock.picking', string="Picking")
    product_id = fields.Many2one(comodel_name='product.template', string="Product")
    product_uom_desc = fields.Char(string="UoM")
    packaging_code = fields.Char(string="Packaging")
    packaging_desc = fields.Char(string="Packaging Description")
    qty_packaging_sap = fields.Float(string="Qty", default=0.0)
    company_id = fields.Many2one(comodel_name='res.company', string="Company")