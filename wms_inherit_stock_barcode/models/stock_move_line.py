from odoo import models, fields, api
from odoo.exceptions import ValidationError
from odoo.tools import float_compare
import logging
_logger = logging.getLogger(__name__)


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    uom_bag_id = fields.Many2one('uom.uom', related='product_id.uom_bag_id', store=True)
    uom_pallet_id = fields.Many2one('uom.uom', related='product_id.uom_pallet_id', store=True)
    bag_qty = fields.Float()
    pallet_qty = fields.Float(compute='_compute_pallet_qty', store=True)
    qty_packaging_sap = fields.Float(default=0.0)
    pallet_status = fields.Selection([
        ('full_pallet', 'Full Pallet'),
        ('eceran', 'Eceran'),
    ], string="Pallet Status", default=False)
    mandatory_destination = fields.Boolean(related='picking_id.picking_type_id.mandatory_destination', readonly=False)
    checker_only = fields.Boolean(related='picking_id.checker_only', store=True)
    checker_out = fields.Boolean(related='picking_id.checker_out', store=True)
    wh_category_id = fields.Many2one(comodel_name='stock.warehouse.category', string="Category")
    suggest_dest_id = fields.Many2one(comodel_name='stock.location', string="Suggest Location")
    dummy_full_pallet = fields.Boolean(string="Dummy Full Pallet", store=False)
    create_new_picking = fields.Boolean(related='picking_id.create_new_picking', store=True)
    autofill_pack_qty = fields.Boolean(related='picking_id.autofill_pack_qty', store=True)
    hide_zero_qty = fields.Boolean(related='picking_id.hide_zero_qty', store=True)
    pallet_ke = fields.Integer(string="Pallet Ke-", default=0)
    check_scan_pallet = fields.Boolean(related='picking_id.check_scan_pallet', store=True)
    order_seq = fields.Integer(related='move_id.order_seq', store=True, string="Order Seq")
    order_selection = fields.Selection(related='move_id.order_selection', store=True, string="Order Selection")
    gratis_locked = fields.Boolean(related='move_id.gratis_locked', string="Gratis Locked")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['outermost_result_package_id'] = False

            self._validate_bag_qty(vals)
            self._sync_qty_from_bag(vals)

        filtered_vals_list = self._filter_empty_package_lines(vals_list)
        if not filtered_vals_list:
            return self.browse()
        records = super().create(filtered_vals_list)
        return records

    def write(self, vals):
        vals['outermost_result_package_id'] = False

        self._validate_bag_qty(vals, records=self)
        self._sync_qty_from_bag(vals, records=self)
        self._validate_qty_packaging_sap(vals)
        # fix negative stock: is_reserved doesn't recompute on cancel/done since it has no real
        # dependency path to stock.move.line state, so trigger it explicitly here
        packages_to_recompute = (self.package_id | self.result_package_id) if 'state' in vals else self.env['stock.package']
        res = super().write(vals)
        if packages_to_recompute:
            packages_to_recompute._compute_is_reserved()
        return res

    def _clear_destination_pallet(self, vals, records=None):
        picking_id = vals.get('picking_id')
        if picking_id:
            picking = self.env['stock.picking'].sudo().browse(picking_id)
            if picking and picking.picking_type_id.split_package:
                vals['result_package_id'] = False
                return # Langsung keluar jika sudah diset

        if records:
            for rec in records:
                if rec.picking_id and rec.picking_id.picking_type_id.split_package:
                    vals['result_package_id'] = False
                    break # Cukup set sekali saja di vals karena vals berlaku untuk semua record di batch ini
    
    def _resolve_hide_zero_qty(self, vals):
        picking_id = vals.get("picking_id")
        if picking_id:
            return self.env["stock.picking"].browse(picking_id).hide_zero_qty
 
        move_id = vals.get("move_id")
        if move_id:
            move = self.env["stock.move"].browse(move_id)
            if move.exists() and move.picking_id:
                return move.picking_id.hide_zero_qty
 
        return False
 
    def _filter_empty_package_lines(self, vals_list):
        filtered_vals = []
        for vals in vals_list:
            hide_zero_qty = self._resolve_hide_zero_qty(vals)
            if not hide_zero_qty:
                filtered_vals.append(vals)
                continue
 
            quantity = vals.get("quantity") or 0
            reserved = vals.get("reserved_uom_qty") or 0
            has_package = bool(vals.get("package_id"))
 
            if has_package and not quantity and not reserved:
                continue
 
            filtered_vals.append(vals)
 
        return filtered_vals

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
            computed_qty = bag_qty * (uom_bag.factor / 1000)
            vals['qty_done'] = computed_qty

    @api.constrains('pallet_qty', 'picking_id')
    def _check_pallet_qty_limit(self):
        for record in self:
            if record.picking_id and record.picking_id.picking_type_id.code != 'outgoing':
                if record.result_package_id and record.pallet_qty > 1:
                    raise ValidationError("Quantity Pallet sudah melebihi UPP Pallet!")
    
    def _validate_qty_packaging_sap(self, vals):
        if 'qty_packaging_sap' not in vals:
            return
        for rec in self:
            value = vals.get('qty_packaging_sap', rec.qty_packaging_sap)
            if value is None or value <= 0:
                raise ValidationError(f"Packaging Qty untuk product {rec.product_id.default_code} tidak boleh kurang dari 0!")
    
    def _validate_bag_qty(self, vals, records=None):
        if 'bag_qty' not in vals:
            return
        bag_qty = vals.get('bag_qty')
        if not bag_qty:
            return
        recs = records or self
        if not recs:
            if bag_qty != int(bag_qty):
                raise ValidationError("Quantity BAG tidak boleh desimal! Masukkan bilangan bulat.")
            return
        for rec in recs:
            if bag_qty != int(bag_qty):
                raise ValidationError(
                    f"Quantity BAG untuk produk {rec.product_id.default_code or rec.product_id.name} "
                    f"tidak boleh desimal! Masukkan bilangan bulat."
                )

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
            'checker_only',
            'checker_out',
            'production_line_id', 
            'first_count', 
            'last_count', 
            'stock_type',
            'create_new_picking',
            'autofill_pack_qty',
            'check_scan_pallet',
            'order_seq',
            'order_selection',
            'gratis_locked',
        ]
    
    def _check_package_capacity_limit(self):
        for line in self:
            if not line.result_package_id:
                continue
            lines = self.sudo().search([
                ('result_package_id', '=', line.result_package_id.id),
                ('product_id', '=', line.product_id.id),
                ('picking_id', '=', line.picking_id.id),
            ])
            total_pallet = sum(lines.mapped('pallet_qty'))
            total_bag = sum(lines.mapped('bag_qty'))
            if total_pallet > 1:
                uom_bag_name = lines[0].uom_bag_id.name if lines and lines[0].uom_bag_id else 'BAG'
                try:
                    max_bag = lines[0].uom_pallet_id.factor / lines[0].uom_bag_id.factor
                except ZeroDivisionError:
                    max_bag = 0
                remaining_bag = max_bag - (total_bag - line.bag_qty)
                raise ValidationError(
                    f"{line.result_package_id.name} sudah melebihi UPP Pallet, "
                    f"hanya bisa ditambah sebanyak {remaining_bag:.0f} {uom_bag_name} lagi!"
                )
                
    def action_fill_full_pallet(self):
        for line in self:
            if line.uom_bag_id and line.uom_pallet_id:
                try:
                    max_bag = int(line.uom_pallet_id.factor / line.uom_bag_id.factor)
                    line.bag_qty = max_bag
                except ZeroDivisionError:
                    pass

    def _synchronize_quant(self, quantity, location, action="available", in_date=False, **quants_value):
        if action == "available" and self.pallet_ke and quantity > 0:
            self = self.with_context(force_pallet_ke=self.pallet_ke)  # insert_pallet_ke
        if action == "available" and self.production_line_id:
            self = self.with_context(force_production_line=self.production_line_id.id)
        return super()._synchronize_quant(quantity, location, action=action, in_date=in_date, **quants_value)