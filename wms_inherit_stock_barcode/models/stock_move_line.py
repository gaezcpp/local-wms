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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['outermost_result_package_id'] = False

            self._validate_bag_qty(vals)
            self._sync_qty_from_bag(vals)

        filtered_vals_list = self._filter_empty_package_lines(vals_list)
        if not filtered_vals_list:
            _logger.info("[WMS-NEGQTY] stock.move.line create DROPPED ALL (hide_zero_qty) vals_list=%s", vals_list)
            return self.browse()
        records = super().create(filtered_vals_list)
        _logger.info(
            "[WMS-NEGQTY] stock.move.line CREATE result=%s",
            [(r.id, r.move_id.id, r.picking_id.id if r.picking_id else False,
              r.quantity, r.bag_qty, r.lot_id.name if r.lot_id else False) for r in records],
        )
        records._validate_lot_availability()
        return records

    def write(self, vals):
        vals['outermost_result_package_id'] = False

        self._validate_bag_qty(vals, records=self)
        self._sync_qty_from_bag(vals, records=self)
        self._validate_qty_packaging_sap(vals)
        if {'quantity', 'bag_qty', 'qty_done'} & set(vals.keys()):
            _logger.info(
                "[WMS-NEGQTY] stock.move.line WRITE ids=%s vals=%s before=%s",
                self.ids, vals,
                [(r.id, r.quantity, r.bag_qty) for r in self],
            )
        res = super().write(vals)

        if {'quantity', 'bag_qty', 'qty_done'} & set(vals.keys()):
            self._validate_lot_availability()

        return res

    def _validate_lot_availability(self):
        """[WMS-NEGQTY] Cegah quantity satu move.line melebihi stok LOT
        spesifik yang benar-benar ada di lokasi sumbernya. Setiap move.line
        terikat ke satu lot tertentu -- kalau user menulis quantity yang
        merepresentasikan total gabungan beberapa lot (mis. hasil tombol
        "fulfill" pada tampilan yang meng-grup beberapa lot jadi satu baris,
        lihat groupKey() di stock_barcode core yang grouping berdasarkan
        product+location TANPA lot) ke satu line berlot tunggal, itu salah:
        line itu akan mencatat lot A seolah sebanyak qty gabungan, padahal
        fisik lot A di lokasi itu jauh lebih sedikit -- baru ketahuan
        belakangan sebagai stock.quant minus (root cause asli kasus ini).
        Divalidasi terhadap stock.quant on-hand dikurangi reservasi line
        lain (state belum done/cancel) untuk lot+lokasi yang sama, ditambah
        qty yang sudah direservasi line ini sendiri sebelumnya."""
        if self.env.context.get('skip_over_demand_check'):
            return

        precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        for line in self:
            if not line.lot_id or not line.location_id or line.state in ('done', 'cancel'):
                continue
            picking_type = line.picking_id.picking_type_id if line.picking_id else False
            if not picking_type or not picking_type.restrict_over_demand:
                continue

            domain = [
                ('product_id', '=', line.product_id.id),
                ('lot_id', '=', line.lot_id.id),
                ('location_id', '=', line.location_id.id),
            ]
            quant_domain = domain + [
                ('package_id', '=', line.package_id.id if line.package_id else False),
            ]
            on_hand = sum(self.env['stock.quant'].sudo().search(quant_domain).mapped('quantity'))

            other_lines = self.env['stock.move.line'].sudo().search(domain + [
                ('id', '!=', line.id),
                ('state', 'not in', ('done', 'cancel')),
            ])
            reserved_by_others = sum(other_lines.mapped('quantity'))
            available_for_line = on_hand - reserved_by_others

            if float_compare(line.quantity, available_for_line, precision_digits=precision) > 0:
                _logger.info(
                    "[WMS-NEGQTY] _validate_lot_availability BLOCKED line=%s move=%s "
                    "picking=%s(id=%s) product=%s lot=%s location=%s on_hand=%s "
                    "reserved_by_others=%s available=%s attempted_qty=%s",
                    line.id, line.move_id.id, line.picking_id.name, line.picking_id.id,
                    line.product_id.display_name, line.lot_id.name, line.location_id.complete_name,
                    on_hand, reserved_by_others, available_for_line, line.quantity,
                )
                raise ValidationError(
                    f"Quantity {line.quantity} yang diinput untuk lot '{line.lot_id.name}' "
                    f"({line.product_id.display_name}) di picking {line.picking_id.name} "
                    f"melebihi stok lot tersebut yang tersedia di lokasi "
                    f"'{line.location_id.complete_name}' (tersedia: {available_for_line}). "
                    f"Input quantity sesuai qty milik lot ini saja, jangan total gabungan lot lain."
                )
    
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
            _logger.info(
                "[WMS-NEGQTY] _sync_qty_from_bag line=%s move=%s picking=%s(id=%s) "
                "bag_qty=%s uom_bag_factor=%s computed_quantity=%s "
                "vals_has_quantity_key=%s vals_quantity_value=%s current_line_quantity=%s",
                rec.id, rec.move_id.id,
                rec.picking_id.name if rec.picking_id else False,
                rec.picking_id.id if rec.picking_id else False,
                bag_qty, uom_bag.factor, computed_qty,
                'quantity' in vals, vals.get('quantity'), rec.quantity,
            )

    @api.constrains('pallet_qty', 'picking_id')
    def _check_pallet_qty_limit(self):
        for record in self:
            if record.picking_id and record.picking_id.picking_type_id.code != 'outgoing':
                if record.result_package_id and record.pallet_qty > 1:
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
            'stock_type',
            'create_new_picking',
            'autofill_pack_qty',
        ]
    
    # @api.constrains('pallet_qty', 'bag_qty', 'result_package_id')
    # def _check_package_capacity_limit(self):
    #     for line in self:
    #         if line.picking_id and line.picking_id.state not in ('done', 'cancel'):
    #             if not line.result_package_id:
    #                 continue

    #             lines = self.sudo().search([
    #                 ('result_package_id', '=', line.result_package_id.id),
    #                 ('product_id', '=', line.product_id.id),
    #                 ('picking_id', '=', line.picking_id.id),
    #             ])
                
    #             total_pallet = sum(lines.mapped('pallet_qty'))
    #             total_bag = sum(lines.mapped('bag_qty'))

    #             if total_pallet > 1:
    #                 uom_bag_name = lines[0].uom_bag_id.name if lines and lines[0].uom_bag_id else 'BAG'
    #                 try:
    #                     max_bag = lines[0].uom_pallet_id.factor / lines[0].uom_bag_id.factor
    #                 except:
    #                     max_bag = 0
                    
    #                 remaining_bag = max_bag - (total_bag - line.bag_qty)
    #                 raise ValidationError(
    #                     f"{line.result_package_id.name} sudah melebihi UPP Pallet, "
    #                     f"hanya bisa ditambah sebanyak {remaining_bag:.0f} {uom_bag_name} lagi!"
    #                 )
    
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
                    # line._onchange_bag_qty()
                except ZeroDivisionError:
                    pass

    def _synchronize_quant(self, quantity, location, action="available", in_date=False, **quants_value):
        if action == "available" and self.pallet_ke and quantity > 0:
            self = self.with_context(force_pallet_ke=self.pallet_ke)  # insert_pallet_ke
        if action == "available" and self.production_line_id:
            self = self.with_context(force_production_line=self.production_line_id.id)
        return super()._synchronize_quant(quantity, location, action=action, in_date=in_date, **quants_value)