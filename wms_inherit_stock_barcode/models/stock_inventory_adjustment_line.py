from odoo import models, fields, api
from odoo.exceptions import ValidationError


class StockInventoryAdjustmentLine(models.Model):
    _name = 'stock.inventory.adjustment.line'
    _description = 'Stock Inventory Adjustment Line'

    stock_adjustment_id = fields.Many2one('stock.inventory.adjustment', ondelete='cascade')
    product_id = fields.Many2one('product.product')
    uom_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    uom_bag_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    location_id = fields.Many2one('stock.location')
    lot_id = fields.Many2one('stock.lot')
    package_id = fields.Many2one('stock.package')
    package_status = fields.Selection([
        ('QI', 'QI'),
        ('BLOCKED', 'BLOCKED'),
        ('UU', 'UU'),
    ], string="Stock Type", default=False)
    zeili = fields.Char(string="Zeili")
    quant_id = fields.Many2one('stock.quant', string="Quant", ondelete='set null')
    quantity = fields.Float(string="On Hand")
    inventory_quantity = fields.Float(string="Count", compute='_compute_from_quant', store=True)
    bag_qty = fields.Float(string="On Hand Bag", compute='_compute_from_quant', store=True)
    bag_count = fields.Float(string="Pack Count", compute='_compute_from_quant', store=True)
    inventory_diff_quantity = fields.Float(string="Diff", compute='_compute_from_quant', store=True)
    
    @api.depends('quant_id', 'quant_id.inventory_quantity', 'quant_id.inventory_diff_quantity')
    def _compute_from_quant(self):
        for line in self:
            quant = line.quant_id
            if quant:
                line.inventory_quantity = quant.inventory_quantity
                line.inventory_diff_quantity = quant.inventory_diff_quantity
                if quant.uom_bag_id and quant.product_uom_id:
                    line.bag_qty = quant.product_uom_id._compute_quantity(quant.quantity, quant.uom_bag_id)
                    line.bag_count = quant.product_uom_id._compute_quantity(quant.inventory_quantity, quant.uom_bag_id)
                else:
                    line.bag_qty = quant.quantity
                    line.bag_count = quant.inventory_quantity
            else:
                line.inventory_quantity = 0.0
                line.inventory_diff_quantity = 0.0
                line.bag_qty = 0.0
                line.bag_count = 0.0