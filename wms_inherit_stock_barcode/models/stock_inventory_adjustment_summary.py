from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class StockInventoryAdjustmentSummary(models.Model):
    _name = 'stock.inventory.adjustment.summary'
    _description = 'Summary Stock Opname'
    
    stock_adjustment_id = fields.Many2one('stock.inventory.adjustment', required=True)
    product_id = fields.Many2one('product.product', required=True)
    sloc_name = fields.Char(string="SLOC Name")
    sloc_id = fields.Many2one(comodel_name='storage.location', string="SLOC")
    stock_type = fields.Selection([
        ('QI', 'QI'),
        ('Blocked', 'Blocked'),
        ('UU', 'UU')], string="Stock Type", default=False)
    quantity = fields.Float(string="Quantity")
    inventory_quantity = fields.Float(string="Inventory Qty")
    inventory_diff_quantity = fields.Float(string="Diff Qty")