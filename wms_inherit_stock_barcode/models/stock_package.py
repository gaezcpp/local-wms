from odoo import models, fields, api


class InheritStockPackage(models.Model):
    _inherit = 'stock.package'
    
    
    can_be_use = fields.Boolean(string="Can Be Use", default=True)