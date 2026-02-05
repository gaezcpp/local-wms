from odoo import models, fields, api


class InheritStockPickingType(models.Model):
    _inherit = 'stock.picking.type'
    
    uu_only = fields.Boolean(string="UU Only", default=False)
    production_only = fields.Boolean(string="Production Only", default=False)