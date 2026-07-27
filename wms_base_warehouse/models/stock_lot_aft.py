from odoo import models, fields, api
from odoo.tools.sql import create_index


class StockLotAft(models.Model):
    _name = 'stock.lot.aft'
    _description = 'Stock Lot Aft'

    lot_id = fields.Many2one(comodel_name='stock.lot', string="Lot Aft")
    quantity = fields.Float(string="Quantity")
    uom_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    bag_qty = fields.Float(string="Quantity")
    uom_bag_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    stock_type = fields.Selection([
        ('QI', 'QI'),
        ('BLOCKED', 'BLOCKED'),
        ('UU', 'UU'),
    ], string="Stock Type", default='QI')