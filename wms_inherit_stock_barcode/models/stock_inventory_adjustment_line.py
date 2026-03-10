from odoo import models, fields, api
from odoo.exceptions import ValidationError


class StockInventoryAdjustmentLine(models.Model):
    _name = 'stock.inventory.adjustment.line'
    _description = 'Stock Inventory Adjustment Line'

    stock_adjustment_id = fields.Many2one('stock.inventory.adjustment', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True)
    location_id = fields.Many2one('stock.location', required=True)
    lot_id = fields.Many2one('stock.lot')
    package_id = fields.Many2one('stock.package')
    quantity = fields.Float()
    inventory_quantity = fields.Float()
    inventory_diff_quantity = fields.Float()