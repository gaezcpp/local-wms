from odoo import models, fields, api
from odoo.exceptions import ValidationError


class StockLot(models.Model):
    _inherit = 'stock.lot'
    
    lot_aft_ids = fields.One2many('stock.lot.aft', 'lot_id', string="Line Aft")
    production_line_id = fields.Many2one(comodel_name='production.line', string="Line")