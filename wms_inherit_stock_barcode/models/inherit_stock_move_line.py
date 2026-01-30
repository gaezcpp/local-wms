from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class InheritStockMoveLineBarcode(models.Model):
    _inherit = 'stock.move.line'

    uom_bag_id = fields.Many2one('uom.uom', string="UoM Bag", related='product_id.uom_bag_id', store=True, tracking=True)
    uom_pallet_id = fields.Many2one('uom.uom', string="UoM Pallet", related='product_id.uom_pallet_id', store=True, tracking=True)
    bag_qty = fields.Float(string="Bag Qty", store=True, tracking=True)
    pallet_qty = fields.Float(string="Pallet Qty", compute='_compute_pallet_qty', store=True, tracking=True)
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            bag_qty = vals.get('bag_qty')
            uom_bag_id = vals.get('uom_bag_id')

            if bag_qty and uom_bag_id:
                uom_bag = self.env['uom.uom'].browse(uom_bag_id)
                vals['quantity'] = bag_qty * uom_bag.relative_factor

            pallet_qty = vals.get('pallet_qty')
            if pallet_qty and pallet_qty > 1:
                raise ValidationError("Quantity Pallet tidak boleh lebih dari 1!")

        return super().create(vals_list)

    def write(self, vals):
        if 'bag_qty' in vals:
            for line in self:
                if line.uom_bag_id:
                    vals['quantity'] = vals['bag_qty'] * line.uom_bag_id.relative_factor

        if 'pallet_qty' in vals and vals['pallet_qty'] > 1:
            raise ValidationError("Quantity Pallet tidak boleh lebih dari 1!")

        return super().write(vals)

    def _get_fields_stock_barcode(self):
        res = super()._get_fields_stock_barcode()
        return res + [
            'bag_qty',
            'pallet_qty',
            'uom_bag_id',
            'uom_pallet_id',
        ]
        
    @api.depends('bag_qty', 'uom_pallet_id')
    def _compute_pallet_qty(self):
        for line in self:
            if line.bag_qty and line.uom_pallet_id:
                line.pallet_qty = line.bag_qty / line.uom_pallet_id.relative_factor
            else:
                line.pallet_qty = 0.0
    
    @api.onchange('bag_qty')
    def _onchange_bag_qty(self):
        for line in self:
            if not line.bag_qty:
                line.qty_done = 0.0
                continue
            
            line.qty_done = line.bag_qty * line.uom_bag_id.relative_factor
    
    # @api.model_create_multi
    # def create(self, vals_list):
    #     for vals in vals_list:
    #         pallet_qty = vals.get('pallet_qty')
    #         if pallet_qty and pallet_qty > 1.0:
    #             raise ValidationError("Quantity Pallet tidak boleh lebih dari 1!!")
    #     return super().create(vals_list)

    # def write(self, vals):
    #     pallet_qty = vals.get('pallet_qty')
    #     if pallet_qty and pallet_qty > 1.0:
    #         raise ValidationError("Quantity Pallet tidak boleh lebih dari 1!")
    #     return super().write(vals)

    # @api.onchange('bag_qty')
    # def _onchange_bag_qty(self):
    #     for line in self:
    #         if not line.bag_qty:
    #             line.pallet_qty = 0.0
    #             line.quantity = 0.0
    #             continue

    #         if not line.uom_bag_id or not line.uom_pallet_id:
    #             line.pallet_qty = 0.0
    #             return

    #         line.pallet_qty = line.bag_qty / line.uom_pallet_id.relative_factor
    #         line.quantity = line.bag_qty * line.uom_bag_id.relative_factor
    
    # @api.depends('quantity', 'uom_bag_id', 'uom_pallet_id')
    # def _compute_bag_qty(self):
    #     for line in self:
    #         if not line.uom_bag_id or not line.quantity:
    #             line.bag_qty = 0.0
    #             continue

    #         line.bag_qty = line.quantity / line.uom_bag_id.relative_factor

    # @api.depends('bag_qty', 'uom_pallet_id')
    # def _compute_pallet_qty(self):
    #     for line in self:
    #         if not line.bag_qty or not line.uom_pallet_id:
    #             line.pallet_qty = 0.0
    #             continue

    #         line.pallet_qty = line.bag_qty / line.uom_pallet_id.relative_factor
    
    # def _inverse_bag_qty(self):
    #     for line in self:
    #         if not line.bag_qty:
    #             line.quantity = 0.0
    #             line.pallet_qty = 0.0
    #             continue

    #         if not line.uom_bag_id or not line.uom_pallet_id:
    #             continue

    #         line.quantity = line.bag_qty * line.uom_bag_id.relative_factor
    #         line.pallet_qty = line.bag_qty / line.uom_pallet_id.relative_factor

    # def _inverse_pallet_qty(self):
    #     for line in self:
    #         if not line.pallet_qty:
    #             line.bag_qty = 0.0
    #             line.quantity = 0.0
    #             continue

    #         if not line.uom_pallet_id or not line.uom_bag_id:
    #             continue

    #         line.bag_qty = line.pallet_qty * line.uom_pallet_id.relative_factor
    #         line.quantity = line.bag_qty * line.uom_bag_id.relative_factor