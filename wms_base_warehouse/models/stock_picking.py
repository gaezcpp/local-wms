from odoo import models, fields, api


class InheritBaseStockPicking(models.Model):
    _inherit = 'stock.picking'
    
    over_delivery = fields.Boolean(string="Over Delivery", tracking=True)
    production_shift_id = fields.Many2one(comodel_name='production.shift', string="Shift", tracking=True)
    production_order_name = fields.Char(string="Production Order", tracking=True)
    product_packaging_ids = fields.One2many('picking.packaging.line', 'picking_id')
    synchronize_sap = fields.Boolean(string="Synchronize SAP", default=False, tracking=True)