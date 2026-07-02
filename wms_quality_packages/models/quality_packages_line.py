from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)

class QualityPackagesLine(models.Model):
    _name = 'quality.packages.line'
    _description = 'Quality Packages Line'
    
    quality_packages_id = fields.Many2one(comodel_name='quality.packages', string="Quality Packages", ondelete='cascade')
    product_id = fields.Many2one(comodel_name='product.product', string="Product")
    package_id = fields.Many2one(comodel_name='stock.package', string="Package")
    location_id = fields.Many2one(comodel_name='stock.location', string="Location")
    lot_id = fields.Many2one(comodel_name='stock.lot', string="Lot")
    quant_id = fields.Many2one(comodel_name='stock.quant', string="Quant")
    quantity = fields.Float(string="Quantity")
    uom_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    bag_qty = fields.Float(string="Quantity")
    uom_bag_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    is_selected = fields.Boolean(string="Selected")
    po_sap_id = fields.Many2one(comodel_name='production.order.sap')