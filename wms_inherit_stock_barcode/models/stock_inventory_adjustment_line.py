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
    system_qty = fields.Float(readonly=True)
    counted_qty = fields.Float()
    difference_qty = fields.Float(compute='_compute_difference')

    @api.depends('system_qty', 'counted_qty')
    def _compute_difference(self):
        for rec in self:
            rec.difference_qty = rec.counted_qty - rec.system_qty