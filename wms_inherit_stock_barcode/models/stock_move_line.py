from odoo import models, fields, api
from odoo.exceptions import ValidationError


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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['outermost_result_package_id'] = False
            
            self._validate_bag_qty(vals)
            self._sync_qty_from_bag(vals)
            
        records = super().create(vals_list)
        return records

    def write(self, vals):
        vals['outermost_result_package_id'] = False
        
        self._validate_bag_qty(vals, records=self)
        self._sync_qty_from_bag(vals, records=self)
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

    @api.constrains('pallet_qty', 'picking_id')
    def _check_pallet_qty_limit(self):
        for record in self:
            if record.picking_id and record.picking_id.picking_type_id.code != 'outgoing':
                if record.pallet_qty > 1:
                    raise ValidationError("Quantity Pallet tidak boleh lebih dari 1!")
    
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
            'stock_type'
        ]
    
    @api.constrains('pallet_qty', 'bag_qty', 'result_package_id')
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
                except:
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
                    # line._onchange_bag_qty()
                except ZeroDivisionError:
                    pass