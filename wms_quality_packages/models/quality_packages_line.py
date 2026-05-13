from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)

class QualityPackagesLine(models.Model):
    _name = 'quality.packages.line'
    _description = 'Quality Packages Line'
    
    quality_packages_id = fields.Many2one(comodel_name='quality.packages', string="Quality Packages")
    package_id = fields.Many2one(comodel_name='stock.package', string="Package")
    location_id = fields.Many2one(comodel_name='stock.location', string="Location")
    lot_id = fields.Many2one(comodel_name='stock.lot', string="Lot")
    quantity = fields.Float(string="Quantity")
    uom_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    bag_qty = fields.Float(string="Bag Qty")
    uom_bag_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    is_selected = fields.Boolean(string="Selected")