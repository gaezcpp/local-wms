from collections import defaultdict

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
        # Nested package tidak dipakai di deployment ini, jadi
        # outermost_result_package_id selalu dipaksa False. Tapi field itu
        # computed+inverse: mengisinya memicu
        # _inverse_outermost_result_package_id() per baris walau tidak ada yang
        # perlu dilepas. Jadi cukup diisi untuk baris yang benar-benar berkaitan
        # dengan package bersarang -- satu browse untuk seluruh batch.
        nested_package_ids = set()
        candidate_ids = {
            vals.get('result_package_id') for vals in vals_list
            if vals.get('result_package_id')
        }
        if candidate_ids:
            packages = self.env['stock.package'].browse(candidate_ids)
            nested_package_ids = {p.id for p in packages if p.package_dest_id}

        for vals in vals_list:
            if vals.get('outermost_result_package_id') or vals.get('result_package_id') in nested_package_ids:
                vals['outermost_result_package_id'] = False

            self._validate_bag_qty(vals)
            self._sync_qty_from_bag(vals)

        filtered_vals_list = self._filter_empty_package_lines(vals_list)
        if not filtered_vals_list:
            return self.browse()
        records = super().create(filtered_vals_list)
        return records

    def _needs_outermost_package_reset(self, vals):
        """True kalau ada nesting package yang benar-benar perlu dilepas.

        Dipakai supaya `outermost_result_package_id = False` hanya ditulis saat
        berpengaruh. `write()` dipanggil puluhan kali per Validate (core menulis
        picked/state/date per baris); tanpa penjagaan ini setiap panggilan ikut
        menjalankan inverse-nya, yang menelusuri rantai package dan menulis
        `package_dest_id` walau tidak ada yang berubah.
        """
        if vals.get('outermost_result_package_id'):
            return True
        return bool(self.result_package_id.package_dest_id)

    def write(self, vals):
        if self._needs_outermost_package_reset(vals):
            vals = dict(vals, outermost_result_package_id=False)

        self._validate_bag_qty(vals, records=self)
        self._sync_qty_from_bag(vals, records=self)
        self._validate_qty_packaging_sap(vals)
        if (
            'quantity' in vals
            and len(self) == 1
            and not self.env.context.get('skip_pallet_lot_spread')
            # Core menulis ulang `quantity` dengan nilai yang sama beberapa kali
            # per Validate. Penyebarannya hanya relevan kalau qty benar-benar
            # berubah, dan pemeriksaan ini menghemat 2 search per penulisan.
            and float_compare(
                vals['quantity'] or 0.0, self.quantity,
                precision_rounding=(self.product_uom_id or self.product_id.uom_id).rounding or 0.01,
            ) != 0
        ):
            # Barcode selalu menulis per baris ((1, id, vals) dari move_line_ids),
            # jadi cukup menangani recordset tunggal; write massal dibiarkan apa
            # adanya dan tetap dijaga _check_package_lot_capacity().
            vals = self._spread_pallet_lot_excess(vals)
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

    def _spread_pallet_lot_excess(self, vals):
        """Pecah kelebihan qty hasil scan pallet ke lot lain di pallet yang sama.

        Aturan bisnisnya: scan satu pallet = ambil seluruh isinya, tapi reservasi
        tiap lot tidak boleh melebihi qty lot itu di pallet tersebut. Client
        Barcode core melanggar aturan kedua: `_findLine()` mencocokkan line hasil
        scan hanya lewat product + package (lot dilewati karena scan pallet tidak
        membawa lot), sehingga qty lot lain menumpuk di satu baris.

        Di sini kelebihannya dikembalikan ke tempat yang benar: baris yang ditulis
        dipotong sampai sebesar isi lot-nya, dan sisanya dipindahkan ke baris lot
        lain di pallet yang sama (dibuat kalau belum ada), juga dibatasi isi lot
        masing-masing. Hasil akhirnya sama dengan yang dilihat operator: seluruh
        isi pallet terambil, tiap lot dengan qty-nya sendiri.

        Dikerjakan di server supaya tidak bergantung pada versi asset JS yang
        ter-cache di scanner.
        """
        self.ensure_one()
        line = self
        if (
            line.state in ('done', 'cancel')
            or not line.package_id
            or not line.lot_id
            or not line.product_id.is_storable
            or not line.location_id
            or line.location_id.should_bypass_reservation()
        ):
            return vals

        uom = line.product_id.uom_id
        asked = line.product_uom_id._compute_quantity(
            vals['quantity'], uom, rounding_method='HALF-UP',
        )
        quants = self.env['stock.quant'].sudo().search([
            ('package_id', '=', line.package_id.id),
            ('location_id', '=', line.location_id.id),
            ('product_id', '=', line.product_id.id),
        ])
        if not quants:
            # Pallet belum berisi produk ini di lokasi tersebut (mis. baris rantai
            # MTO yang barangnya belum tiba): kapasitasnya belum bisa dinilai.
            return vals

        capacity = sum(quants.filtered(lambda q: q.lot_id == line.lot_id).mapped('quantity'))
        excess = asked - capacity
        if float_compare(excess, 0.0, precision_rounding=uom.rounding) <= 0:
            return vals

        siblings = self.search([
            ('id', '!=', line.id),
            ('move_id', '=', line.move_id.id),
            ('package_id', '=', line.package_id.id),
            ('location_id', '=', line.location_id.id),
            ('state', 'not in', ('done', 'cancel')),
        ])
        result_package = (
            line.result_package_id.id
            if line.result_package_id == line.package_id
            else False
        )

        other_quants = quants.filtered(
            lambda q: q.lot_id and q.lot_id != line.lot_id and q.quantity > 0
        ).sorted(key=lambda q: -q.quantity)
        for quant in other_quants:
            if float_compare(excess, 0.0, precision_rounding=uom.rounding) <= 0:
                break
            lot_lines = siblings.filtered(lambda l: l.lot_id == quant.lot_id)
            booked = sum(lot_lines.mapped('quantity_product_uom'))
            take = min(quant.quantity - booked, excess)
            if float_compare(take, 0.0, precision_rounding=uom.rounding) <= 0:
                continue

            if lot_lines:
                target = lot_lines[0]
                target.with_context(skip_pallet_lot_spread=True).write({
                    'quantity': uom._compute_quantity(
                        booked + take, target.product_uom_id, rounding_method='HALF-UP',
                    ),
                })
            else:
                self.with_context(skip_pallet_lot_spread=True).create({
                    'move_id': line.move_id.id,
                    'picking_id': line.picking_id.id,
                    'product_id': line.product_id.id,
                    'product_uom_id': line.product_uom_id.id,
                    'quantity': uom._compute_quantity(
                        take, line.product_uom_id, rounding_method='HALF-UP',
                    ),
                    'lot_id': quant.lot_id.id,
                    'package_id': line.package_id.id,
                    'result_package_id': result_package,
                    'location_id': line.location_id.id,
                    'location_dest_id': line.location_dest_id.id,
                    'owner_id': quant.owner_id.id or False,
                    'company_id': line.company_id.id,
                    'picked': vals.get('picked', line.picked),
                    'production_line_id': quant.production_line_id.id or False,
                    'pallet_ke': quant.pallet_ke or 0,
                })
            _logger.info(
                "[PALLET-LOT] pallet %s: %s %s dipindahkan dari baris lot %s ke lot %s",
                line.package_id.name, take, uom.name, line.lot_id.name, quant.lot_id.name,
            )
            excess -= take

        if float_compare(excess, 0.0, precision_rounding=uom.rounding) > 0:
            # Sisa yang tidak muat di lot mana pun: biarkan tetap di vals supaya
            # _check_package_lot_capacity() yang menolak dengan pesan lengkap.
            return vals

        vals = dict(vals, quantity=uom._compute_quantity(
            capacity, line.product_uom_id, rounding_method='HALF-UP',
        ))
        return vals

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
        packed = self.filtered('result_package_id')
        if not packed:
            return

        # Satu search untuk semua baris, bukan satu search per baris: pemeriksaan
        # ini dijalankan di akhir setiap button_validate, jadi jumlah query-nya
        # dulu tumbuh linear terhadap jumlah move line.
        siblings = self.sudo().search([
            ('result_package_id', 'in', packed.result_package_id.ids),
            ('product_id', 'in', packed.product_id.ids),
            ('picking_id', 'in', packed.picking_id.ids),
        ])
        grouped = defaultdict(lambda: self.env['stock.move.line'])
        for sibling in siblings:
            key = (sibling.result_package_id.id, sibling.product_id.id, sibling.picking_id.id)
            grouped[key] |= sibling

        for line in packed:
            lines = grouped.get(
                (line.result_package_id.id, line.product_id.id, line.picking_id.id),
            )
            if not lines:
                continue
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