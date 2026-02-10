from odoo import models, fields, api


class InheritStockMove(models.Model):
    _inherit = 'stock.move'

    uom_bag_id = fields.Many2one('uom.uom',  related='product_id.uom_bag_id', store=True, tracking=True)
    uom_pallet_id = fields.Many2one('uom.uom', related='product_id.uom_pallet_id', store=True, tracking=True)
    bag_qty = fields.Float(string="Bag Qty", compute="_compute_bag_qty", store=True, tracking=True)
    pallet_qty = fields.Float(string="Pallet Qty", compute="_compute_pallet_qty", store=True, tracking=True)

    def _get_fields_stock_barcode(self):
        res = super()._get_fields_stock_barcode()
        return res + [
            'bag_qty',
            'pallet_qty',
            'uom_bag_id',
            'uom_pallet_id',
        ]
        
    @api.depends('quantity', 'uom_bag_id', 'uom_pallet_id')
    def _compute_bag_qty(self):
        for line in self:
            if not line.uom_bag_id or not line.quantity:
                line.bag_qty = 0.0
                continue

            line.bag_qty = line.quantity / (line.uom_bag_id.factor / 1000)

    @api.depends('quantity', 'uom_pallet_id')
    def _compute_pallet_qty(self):
        for line in self:
            if not line.quantity or not line.uom_pallet_id:
                line.pallet_qty = 0.0
                continue

            line.pallet_qty = line.quantity / (line.uom_pallet_id.factor / 1000)