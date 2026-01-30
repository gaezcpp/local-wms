from odoo import models, fields, api


class InheritStockPicking(models.Model):
    _inherit = 'stock.picking'
    
    
    over_delivery = fields.Boolean(string="Over Delivery", tracking=True)