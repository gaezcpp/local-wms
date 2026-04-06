from odoo import models, fields, api


class InheritStockMove(models.Model):
    _inherit = 'stock.move'

    uom_bag_id = fields.Many2one('uom.uom',  related='product_id.uom_bag_id', store=True)
    uom_pallet_id = fields.Many2one('uom.uom', related='product_id.uom_pallet_id', store=True)
    bag_qty = fields.Float(string="Bag Qty", compute="_compute_bag_qty", store=True)
    pallet_qty = fields.Float(string="Pallet Qty", compute="_compute_pallet_qty", store=True)

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
    
    # ini untuk next transfer
    def _get_new_picking_values(self):
        vals = super()._get_new_picking_values()

        picking = self[:1].picking_id  # ambil representatif

        if picking:
            vals.update({
                'po_sap_id': picking.po_sap_id.id,
                'production_shift_id': picking.production_shift_id.id,
            })

        return vals
    
    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        res = super()._prepare_move_line_vals(
            quantity=quantity,
            reserved_quant=reserved_quant
        )

        if not self.move_orig_ids:
            return res

        origin_lines = self.move_orig_ids.move_line_ids
        matched_line = False

        if reserved_quant:
            if reserved_quant.package_id:
                matched_line = origin_lines.filtered(
                    lambda l: l.package_history_id.id == reserved_quant.package_id.id
                )[:1]

            if not matched_line and reserved_quant.package_id:
                matched_line = origin_lines.filtered(
                    lambda l: l.result_package_id.id == reserved_quant.package_id.id
                )[:1]

            if not matched_line and reserved_quant.lot_id:
                matched_line = origin_lines.filtered(
                    lambda l: l.lot_id.id == reserved_quant.lot_id.id
                )[:1]

        if not matched_line and origin_lines:
            matched_line = origin_lines.filtered(
                lambda l: l.product_id == self.product_id and l.qty_done == quantity
            )[:1]

        if not matched_line and origin_lines:
            matched_line = origin_lines[:1]

        if matched_line:
            res.update({
                'production_line_id': matched_line.production_line_id.id,
                'first_count': matched_line.first_count,
                'last_count': matched_line.last_count,
                'detail_text': matched_line.detail_text,
            })

        return res