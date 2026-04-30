from odoo import models, fields, api
from odoo.exceptions import ValidationError

class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    uom_bag_id = fields.Many2one('uom.uom', related='product_id.uom_bag_id', store=True)
    uom_pallet_id = fields.Many2one('uom.uom', related='product_id.uom_pallet_id', store=True)
    bag_qty = fields.Float(string="BagQty", compute='_compute_packaging_quantities', inverse='_inverse_bag_qty', store=True)
    pallet_qty = fields.Float(compute='_compute_packaging_quantities', store=True)
    qty_packaging_sap = fields.Float(default=0.0)

    @api.depends('qty_done', 'product_uom_id', 'uom_bag_id', 'uom_pallet_id')
    def _compute_packaging_quantities(self):
        for line in self:
            if line.qty_done and line.product_uom_id:
                if line.uom_bag_id and line.uom_bag_id.factor:
                    line.bag_qty = (line.qty_done * line.product_uom_id.factor / line.uom_bag_id.factor) * 1000
                else:
                    line.bag_qty = 0.0

                if line.uom_pallet_id and line.uom_pallet_id.factor:
                    line.pallet_qty = (line.qty_done * line.product_uom_id.factor / line.uom_pallet_id.factor) * 1000
                else:
                    line.pallet_qty = 0.0
            else:
                line.bag_qty = 0.0
                line.pallet_qty = 0.0

    def _inverse_bag_qty(self):
        for line in self:
            if line.bag_qty and line.uom_bag_id and line.product_uom_id and line.product_uom_id.factor:
                line.qty_done = (line.bag_qty / 1000.0) * line.uom_bag_id.factor / line.product_uom_id.factor
            elif not line.bag_qty:
                line.qty_done = 0.0

    @api.constrains('pallet_qty')
    def _check_pallet_qty(self):
        for rec in self:
            if rec.pallet_qty > 1:
                raise ValidationError("Quantity Pallet tidak boleh lebih dari 1!")
    
    @api.constrains('qty_packaging_sap')
    def _check_qty_packaging_sap(self):
        for rec in self:
            if rec.qty_packaging_sap < 0:
                raise ValidationError(f"Packaging Qty untuk product {rec.product_id.default_code} tidak boleh kurang dari 0!")

    def _get_fields_stock_barcode(self):
        return super()._get_fields_stock_barcode() + [
            'bag_qty',
            'pallet_qty',
            'uom_bag_id',
            'uom_pallet_id',
            'qty_packaging_sap',
        ]