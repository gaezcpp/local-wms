from odoo import models, fields, api
from odoo.exceptions import ValidationError


class StockLot(models.Model):
    _inherit = 'stock.lot'
    
    stock_type = fields.Selection([
        ('QI', 'QI'),
        ('BLOCKED', 'BLOCKED'),
        ('UU', 'UU'),
    ], string="Stock Type", default='QI', tracking=True)