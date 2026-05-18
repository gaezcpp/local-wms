from odoo import models, fields, api
from odoo.exceptions import ValidationError


class StockLot(models.Model):
    _inherit = 'stock.lot'
    
    lot_aft_ids = fields.One2many('stock.lot.aft', 'lot_id', string="Line Aft")