from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class InheritStockMoveLineBarcode(models.Model):
    _inherit = 'stock.move.line'

    uom_bag_id = fields.Many2one('uom.uom', string="UoM Bag", related='product_id.uom_bag_id', tracking=True)
    uom_pallet_id = fields.Many2one('uom.uom', string="UoM Pallet", related='product_id.uom_pallet_id', tracking=True)
    bag_qty = fields.Float(string="Bag Qty", tracking=True)
    pallet_qty = fields.Float(string="Pallet Qty", tracking=True)
    
    def _get_fields_stock_barcode(self):
        res = super()._get_fields_stock_barcode()
        return res + [
            'bag_qty',
            'pallet_qty',
            'uom_bag_id',
            'uom_pallet_id',
        ]
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            pallet_qty = vals.get('pallet_qty')
            if pallet_qty and pallet_qty > 1.0:
                raise ValidationError("Quantity Pallet tidak boleh lebih dari 1!!")
        return super().create(vals_list)

    def write(self, vals):
        pallet_qty = vals.get('pallet_qty')
        if pallet_qty and pallet_qty > 1.0:
            raise ValidationError("Quantity Pallet tidak boleh lebih dari 1!")
        return super().write(vals)
    
    @api.onchange('bag_qty', 'pallet_qty')
    def onchange_convert_bag_pallet(self):
        for line in self:
            line.pallet_qty = 0
            line.qty_done = 0
            
            if (line.bag_qty > 0 and line.uom_bag_id and line.uom_pallet_id):
                line.pallet_qty = line.bag_qty / line.uom_pallet_id.relative_factor
                line.qty_done = line.bag_qty * line.uom_bag_id.relative_factor
                print(f"FUNGSI 1 = {line.pallet_qty} ||| {line.qty_done}")
            else:
                line.qty_done = 0