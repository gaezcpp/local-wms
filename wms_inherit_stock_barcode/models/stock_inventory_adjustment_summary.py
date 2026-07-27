from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class StockInventoryAdjustmentSummary(models.Model):
    _name = 'stock.inventory.adjustment.summary'
    _description = 'Summary Stock Opname'
    
    stock_adjustment_id = fields.Many2one('stock.inventory.adjustment', ondelete='cascade')
    product_id = fields.Many2one('product.product')
    uom_id = fields.Many2one('uom.uom')
    uom_bag_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    sloc_name = fields.Char(string="SLOC Name")
    sloc_id = fields.Many2one(comodel_name='storage.location', string="SLOC")
    stock_type = fields.Selection([
        ('QI', 'QI'),
        ('Blocked', 'Blocked'),
        ('UU', 'UU')], string="Stock Type", default=False)
    zeili = fields.Char(string="Zeili")
    quant_id = fields.Many2one('stock.quant', string="Quant", ondelete='set null')
    quantity = fields.Float(string="On Hand")
    inventory_quantity = fields.Float(string="Count")
    bag_qty = fields.Float(string="On Hand Bag")
    bag_count = fields.Float(string="Pack Count")
    inventory_diff_quantity = fields.Float(string="Diff")