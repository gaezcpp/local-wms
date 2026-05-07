from odoo import models, fields, api
from odoo.exceptions import ValidationError


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    uom_bag_id = fields.Many2one('uom.uom', related='product_id.uom_bag_id', store=True)
    uom_pallet_id = fields.Many2one('uom.uom', related='product_id.uom_pallet_id', store=True)
    bag_qty = fields.Float()
    pallet_qty = fields.Float(compute='_compute_pallet_qty', store=True)
    qty_packaging_sap = fields.Float(default=0.0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._sync_qty_from_bag(vals)
            self._validate_pallet(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._sync_qty_from_bag(vals, records=self)
        self._validate_pallet(vals)
        self._validate_qty_packaging_sap(vals)
        res = super().write(vals)
        return res

    def _sync_qty_from_bag(self, vals, records=None):
        if 'bag_qty' not in vals:
            return

        bag_qty = vals.get('bag_qty')
        if not bag_qty:
            return

        recs = records or self

        for rec in recs:
            uom_bag = rec.uom_bag_id
            if not uom_bag or not uom_bag.factor:
                continue

            vals['qty_done'] = bag_qty * (uom_bag.factor / 1000)

    def _validate_pallet(self, vals):
        if vals.get('pallet_qty', 0) > 1:
            raise ValidationError("Quantity Pallet tidak boleh lebih dari 1!")
    
    def _validate_qty_packaging_sap(self, vals):
        if 'qty_packaging_sap' not in vals:
            return

        for rec in self:
            value = vals.get('qty_packaging_sap', rec.qty_packaging_sap)
            if value is None or value <= 0:
                raise ValidationError(f"Packaging Qty untuk product {rec.product_id.default_code} tidak boleh kurang dari 0!")

    @api.depends('qty_done', 'uom_pallet_id')
    def _compute_pallet_qty(self):
        for line in self:
            if line.qty_done and line.uom_pallet_id:
                line.pallet_qty = line.qty_done / (line.uom_pallet_id.factor / 1000)
            else:
                line.pallet_qty = 0.0

    @api.onchange('bag_qty')
    def _onchange_bag_qty(self):
        for line in self:
            if not line.bag_qty:
                line.qty_done = 0.0
                continue

            if line.uom_bag_id and line.uom_bag_id.factor:
                line.qty_done = line.bag_qty * (line.uom_bag_id.factor / 1000)

    def _get_fields_stock_barcode(self):
        return super()._get_fields_stock_barcode() + [
            'bag_qty',
            'pallet_qty',
            'uom_bag_id',
            'uom_pallet_id',
            'qty_packaging_sap',
        ]