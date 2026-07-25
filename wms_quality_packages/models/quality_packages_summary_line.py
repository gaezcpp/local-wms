from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)

class QualityPackagesSummaryLine(models.Model):
    _name = 'quality.packages.summary.line'
    _description = 'Quality Packages Summary Line'
    
    quality_packages_id = fields.Many2one(comodel_name='quality.packages', string="Quality Packages", ondelete='cascade')
    product_id = fields.Many2one(comodel_name='product.product', string="Product")
    package_id = fields.Many2one(comodel_name='stock.package', string="Package")
    location_id = fields.Many2one(comodel_name='stock.location', string="Location")
    lot_id = fields.Many2one(comodel_name='stock.lot', string="Production Code")
    quantity = fields.Float(string="Quantity")
    uom_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    bag_qty = fields.Float(string="Quantity")
    uom_bag_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    stock_type_from = fields.Selection([
        ('QI', 'QI'),
        ('BLOCKED', 'BLOCKED'),
        ('UU', 'UU'),
    ], string="Stock Type From")
    stock_type_to = fields.Selection([
        ('QI', 'QI'),
        ('BLOCKED', 'BLOCKED'),
        ('UU', 'UU'),
    ], string="Stock Type To")
    move_type = fields.Char(string="Move Type")
    po_sap_id = fields.Many2one(comodel_name='production.order.sap')
    pallet_ke = fields.Integer(string="Pallet Ke-")