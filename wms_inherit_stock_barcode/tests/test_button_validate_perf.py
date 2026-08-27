"""Benchmark `stock.picking.button_validate()` dengan seluruh layer custom aktif.

Tujuan file ini bukan menguji kebenaran (itu ada di test_outbound_barcode.py /
test_pick_package_multi_lot.py) tapi **mengukur** berapa lama satu Validate
berjalan dan di method custom mana waktunya habis.

Instrumentasi memakai patch level-kelas: tiap method custom yang dipanggil di
jalur Validate dibungkus timer + penghitung query (`cr.sql_log_count`). Karena
method-method itu saling memanggil, angka yang dilaporkan bersifat **inklusif**
(termasuk waktu anak-anaknya), jadi bacalah sebagai "berapa mahal cabang ini",
bukan sebagai partisi yang jumlahnya = total.

Jalankan:

    D:\\CPP\\Odoo19-ENT\\python\\python.exe odoo-bin -c wms.conf \\
        -u wms_inherit_stock_barcode --test-enable --test-tags wms_perf \\
        --stop-after-init --no-http

Hasil pengukuran di DB_WMS_DEV_008 (2026-08-25), sebelum vs sesudah putaran
optimasi Validate (batching query di wms_base_warehouse / wms_inherit_stock_barcode
/ wms_production_order_sap):

    skenario           sebelum            sesudah            selisih
    GR Prod 1 baris    0.573 s / 190 q    0.259 s / 154 q    -55% waktu, -19% query
    GR Prod 5 baris    1.296 s / 520 q    0.619 s / 326 q    -52% waktu, -37% query
    PICK 1 baris       0.414 s / 227 q    0.309 s / 205 q    -25% waktu, -10% query
    PICK 10 baris      2.108 s / 905 q    1.074 s / 686 q    -49% waktu, -24% query

Sisa waktunya sekarang didominasi `stock.move._action_done()` bawaan Odoo,
bukan lagi layer custom.
"""

import functools
import logging
import time

from odoo.tests import TransactionCase, tagged

_logger = logging.getLogger(__name__)


class Probe:
    """Bungkus method di kelas Python asalnya, catat durasi + jumlah query."""

    def __init__(self, env):
        self.env = env
        self.stats = {}
        self._patched = []
        self.enabled = False

    def wrap(self, cls, name, label=None):
        label = label or "%s.%s" % (cls.__name__, name)
        original = cls.__dict__.get(name)
        if original is None:
            raise ValueError("%s tidak mendefinisikan %s" % (cls.__name__, name))
        probe = self

        def wrapper(records, *args, **kwargs):
            if not probe.enabled:
                return original(records, *args, **kwargs)
            cr = records.env.cr
            q0 = cr.sql_log_count
            t0 = time.perf_counter()
            try:
                return original(records, *args, **kwargs)
            finally:
                entry = probe.stats.setdefault(label, {'calls': 0, 'time': 0.0, 'queries': 0})
                entry['calls'] += 1
                entry['time'] += time.perf_counter() - t0
                entry['queries'] += cr.sql_log_count - q0

        functools.update_wrapper(wrapper, original)
        setattr(cls, name, wrapper)
        self._patched.append((cls, name, original))

    def restore(self):
        for cls, name, original in reversed(self._patched):
            setattr(cls, name, original)
        self._patched.clear()

    def reset(self):
        self.stats.clear()

    def report(self, title, total_time, total_queries):
        rows = sorted(self.stats.items(), key=lambda kv: kv[1]['time'], reverse=True)
        lines = [
            "",
            "=" * 78,
            "PERF %s" % title,
            "  TOTAL: %.3f s / %d query" % (total_time, total_queries),
            "-" * 78,
            "  %-46s %6s %9s %8s" % ("method (inklusif)", "calls", "time(s)", "queries"),
        ]
        for label, entry in rows:
            if entry['time'] < 0.0005 and entry['queries'] == 0:
                continue
            lines.append("  %-46s %6d %9.3f %8d" % (
                label, entry['calls'], entry['time'], entry['queries'],
            ))
        lines.append("=" * 78)
        _logger.info("\n".join(lines))
        return rows


@tagged('post_install', '-at_install', 'wms_perf')
class TestButtonValidatePerf(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = cls.env['res.company'].search([('name', 'like', '1601')], limit=1)
        if not cls.company:
            raise ValueError("Company 1601 tidak ditemukan di database ini.")

        cls.env.user.write({
            'company_ids': [(4, cls.company.id)],
            'company_id': cls.company.id,
        })
        cls.env = cls.env(context=dict(
            cls.env.context,
            allowed_company_ids=[cls.company.id],
        ))

        PickingType = cls.env['stock.picking.type']
        cls.type_gr = PickingType.search([
            ('company_id', '=', cls.company.id),
            ('sequence_code', '=', 'In-Prod-FG'),
        ], limit=1)
        cls.type_pick = PickingType.search([
            ('company_id', '=', cls.company.id),
            ('sequence_code', '=', 'PICK'),
            ('uu_only', '=', True),
        ], limit=1)
        if not cls.type_gr or not cls.type_pick:
            raise ValueError("Operation type In-Prod-FG / PICK tidak ditemukan.")

        reference = cls.env['product.product'].search([
            ('uom_bag_id', '!=', False),
            ('uom_pallet_id', '!=', False),
            ('tracking', '=', 'lot'),
        ], limit=1)
        if not reference:
            raise ValueError("Tidak ada produk dengan UoM Bag & Pallet sebagai acuan.")

        cls.product = cls.env['product.product'].create({
            'name': 'UT Perf Product',
            'default_code': 'UT-PERF-01',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'lot',
            'uom_id': reference.uom_id.id,
            'uom_bag_id': reference.uom_bag_id.id,
            'uom_pallet_id': reference.uom_pallet_id.id,
            # Format lot company ini (production.code) memakai
            # moveline.expiration_date, jadi produk harus punya masa simpan.
            'use_expiration_date': True,
            'expiration_time': 180,
            'use_time': 150,
            'removal_time': 120,
            'alert_time': 90,
        })

        cls.production_lines = cls.env['production.line'].search([
            ('company_id', '=', cls.company.id),
        ], limit=2)
        if len(cls.production_lines) < 2:
            raise ValueError("Butuh minimal dua production.line pada company ini.")

        cls.shift = cls.env['production.shift'].search([], limit=1)

        cls.loc_stock = cls.type_pick.default_location_src_id
        cls.loc_bin = cls.env['stock.location'].create({
            'name': 'UT-PERF-BIN',
            'location_id': cls.loc_stock.id,
            'usage': 'internal',
            'company_id': cls.company.id,
        })

        cls.qty_per_pallet = 1280.0

    # ------------------------------------------------------------------
    # instrumentasi
    # ------------------------------------------------------------------
    def _build_probe(self):
        from odoo.addons.mail.models.mail_thread import MailThread
        from odoo.addons.stock.models.stock_move import StockMove as CoreMove
        from odoo.addons.stock.models.stock_move_line import StockMoveLine as CoreMoveLine
        from odoo.addons.stock.models.stock_picking import StockPicking as CorePicking
        from odoo.addons.wms_base_warehouse.models.stock_move import StockMove as WbwMove
        from odoo.addons.wms_base_warehouse.models.stock_move_line import (
            InheritBaseStockMoveLine as WbwMoveLine,
        )
        from odoo.addons.wms_base_warehouse.models.stock_picking import (
            InheritBaseStockPicking as WbwPicking,
        )
        from odoo.addons.wms_inherit_stock_barcode.models.stock_move_line import (
            StockMoveLine as SbMoveLine,
        )
        from odoo.addons.wms_inherit_stock_barcode.models.stock_quant import (
            InheritStockQuant as SbQuant,
        )
        from odoo.addons.wms_inherit_stock_barcode.models.stock_picking import (
            StockPicking as SbPicking,
        )
        from odoo.addons.wms_production_order_sap.models.stock_picking import (
            InheritBaseStockPicking as PosPicking,
        )

        probe = Probe(self.env)
        for name in (
            'button_validate', '_sync_packaging_lines', '_prepare_packaging_lines_vals',
            '_check_all_result_package_id', '_check_production_order_sap',
            'remove_package_customer_location', 'restrict_customer_location',
            '_has_missing_qty', '_sync_post_validate_quantities',
            '_fill_next_transfer_result_package', '_pre_action_done_hook',
            '_get_next_pallet_ke_map',
        ):
            probe.wrap(SbPicking, name, 'barcode.picking.%s' % name)
        probe.wrap(SbMoveLine, '_check_package_capacity_limit', 'barcode.line._check_package_capacity_limit')
        for name in ('button_validate', '_check_restrict_over_demand', 'cancel_unprocessed_picking', '_is_gr_prod'):
            probe.wrap(WbwPicking, name, 'basewh.picking.%s' % name)
        probe.wrap(WbwMove, '_action_done', 'basewh.move._action_done')
        probe.wrap(WbwMoveLine, '_action_done', 'basewh.line._action_done')
        probe.wrap(PosPicking, 'button_validate', 'posap.picking.button_validate')
        probe.wrap(MailThread, 'message_post', 'mail.message_post')
        # Layer core sebagai pembanding: selisih custom - core = overhead custom.
        probe.wrap(CorePicking, 'button_validate', 'CORE.picking.button_validate')
        probe.wrap(CorePicking, '_action_done', 'CORE.picking._action_done')
        probe.wrap(CoreMove, '_action_done', 'CORE.move._action_done')
        probe.wrap(CoreMoveLine, '_action_done', 'CORE.line._action_done')
        # Write/create custom yang ikut kena setiap Validate.
        probe.wrap(SbQuant, 'write', 'barcode.quant.write')
        probe.wrap(SbQuant, 'create', 'barcode.quant.create')
        probe.wrap(SbMoveLine, 'write', 'barcode.line.write')
        probe.wrap(SbMoveLine, 'create', 'barcode.line.create')
        probe.wrap(WbwMoveLine, 'write', 'basewh.line.write')
        probe.wrap(WbwMoveLine, 'create', 'basewh.line.create')

        # `stock.quant.create/write` custom dimatikan sendiri saat --test-enable
        # (`_skip_custom_logic`). Untuk benchmark itu harus dinyalakan, kalau
        # tidak angkanya tidak mewakili produksi.
        original_skip = SbQuant.__dict__['_skip_custom_logic']
        SbQuant._skip_custom_logic = lambda records: False
        self.addCleanup(setattr, SbQuant, '_skip_custom_logic', original_skip)

        self.addCleanup(probe.restore)
        return probe

    def _measure(self, probe, title, picking, context=None):
        # `test_stock_no_negative` mengaktifkan kembali constraint stok negatif
        # yang modul stock_no_negative matikan saat --test-enable.
        picking = picking.with_context(test_stock_no_negative=True, **(context or {}))
        self.env.flush_all()
        probe.reset()
        probe.enabled = True
        cr = self.env.cr
        q0 = cr.sql_log_count
        t0 = time.perf_counter()
        res = picking.button_validate()
        self.env.flush_all()
        elapsed = time.perf_counter() - t0
        queries = cr.sql_log_count - q0
        probe.enabled = False
        probe.report(title, elapsed, queries)
        self.assertNotIsInstance(res, dict, "button_validate minta wizard: %s" % res)
        self.assertEqual(picking.state, 'done')
        return elapsed, queries

    # ------------------------------------------------------------------
    # fixture builder
    # ------------------------------------------------------------------
    def _make_po_sap(self, order_qty):
        return self.env['production.order.sap'].create({
            'po_number': 'UT-PERF-PO-%d' % int(order_qty),
            'product_id': self.product.id,
            'uom_id': self.product.uom_id.id,
            'order_qty': order_qty,
            'company_id': self.company.id,
            'state': 'open',
        })

    def _make_gr_picking(self, n_lines):
        """Inbound FG Production: production_only + GR (stock.lot.aft path)."""
        qty = self.qty_per_pallet
        po_sap = self._make_po_sap(qty * n_lines * 10)
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.type_gr.id,
            'location_id': self.type_gr.default_location_src_id.id,
            'location_dest_id': self.type_gr.default_location_dest_id.id,
            'company_id': self.company.id,
            'po_sap_id': po_sap.id,
            'production_shift_id': self.shift.id if self.shift else False,
        })
        self.env['stock.move'].create({
            'picking_id': picking.id,
            'product_id': self.product.id,
            'product_uom_qty': qty * n_lines,
            'product_uom': self.product.uom_id.id,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
            'company_id': self.company.id,
        })
        picking.action_confirm()
        picking.move_line_ids.unlink()

        vals_list = []
        for idx in range(n_lines):
            lot = self.env['stock.lot'].create({
                'name': 'UT-PERF-LOT-%d-%d' % (n_lines, idx),
                'product_id': self.product.id,
                'company_id': self.company.id,
            })
            package = self.env['stock.package'].create({
                'name': 'UT-PERF-PKG-%d-%d' % (n_lines, idx),
                'company_id': self.company.id,
            })
            vals_list.append((0, 0, {
                'picking_id': picking.id,
                'product_id': self.product.id,
                'product_uom_id': self.product.uom_id.id,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
                'lot_id': lot.id,
                'result_package_id': package.id,
                'production_line_id': self.production_lines[idx % 2].id,
                'stock_type': 'QI',
                'quantity': qty,
                'picked': True,
            }))
        picking.write({'move_line_ids': vals_list})
        return picking

    def _make_pallet(self, name, production_line, qty=None):
        qty = self.qty_per_pallet if qty is None else qty
        package = self.env['stock.package'].create({
            'name': name,
            'company_id': self.company.id,
        })
        package.yellow_tag = 'ready'
        lot = self.env['stock.lot'].create({
            'name': 'UT-PERF-PICKLOT-%s' % name,
            'product_id': self.product.id,
            'company_id': self.company.id,
        })
        self.env['stock.quant']._update_available_quantity(
            self.product, self.loc_bin, qty, lot_id=lot, package_id=package,
        )
        quant = self.env['stock.quant'].sudo().search([
            ('product_id', '=', self.product.id),
            ('location_id', '=', self.loc_bin.id),
            ('lot_id', '=', lot.id),
            ('package_id', '=', package.id),
        ], limit=1)
        quant.write({'stock_type': 'UU', 'production_line_id': production_line.id})
        return package

    def _make_pick_picking(self, n_lines):
        for idx in range(n_lines):
            self._make_pallet('UT-PERF-PLT-%d-%d' % (n_lines, idx), self.production_lines[idx % 2])
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.type_pick.id,
            'location_id': self.type_pick.default_location_src_id.id,
            'location_dest_id': self.type_pick.default_location_dest_id.id,
            'company_id': self.company.id,
        })
        self.env['stock.move'].create({
            'picking_id': picking.id,
            'product_id': self.product.id,
            'product_uom_qty': self.qty_per_pallet * n_lines,
            'product_uom': self.product.uom_id.id,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
            'company_id': self.company.id,
        })
        picking.action_confirm()
        picking.action_assign()
        picking.move_line_ids.write({'picked': True})
        return picking

    # ------------------------------------------------------------------
    # benchmark
    # ------------------------------------------------------------------
    def test_perf_01_gr_production_single_line(self):
        probe = self._build_probe()
        picking = self._make_gr_picking(1)
        elapsed, queries = self._measure(
            probe, "GR Production (In-Prod-FG) 1 move line", picking,
            context={'pallet_ke_confirmed': True},
        )
        _logger.info("[PERF-RESULT] gr_1_line elapsed=%.3fs queries=%d", elapsed, queries)

    def test_perf_02_gr_production_five_lines(self):
        probe = self._build_probe()
        picking = self._make_gr_picking(5)
        elapsed, queries = self._measure(
            probe, "GR Production (In-Prod-FG) 5 move line", picking,
            context={'pallet_ke_confirmed': True},
        )
        _logger.info("[PERF-RESULT] gr_5_lines elapsed=%.3fs queries=%d", elapsed, queries)

    def test_perf_03_pick_single_line(self):
        probe = self._build_probe()
        picking = self._make_pick_picking(1)
        elapsed, queries = self._measure(probe, "PICK 1 move line", picking)
        _logger.info("[PERF-RESULT] pick_1_line elapsed=%.3fs queries=%d", elapsed, queries)

    def test_perf_04_pick_ten_lines(self):
        probe = self._build_probe()
        picking = self._make_pick_picking(10)
        elapsed, queries = self._measure(probe, "PICK 10 move line", picking)
        _logger.info("[PERF-RESULT] pick_10_lines elapsed=%.3fs queries=%d", elapsed, queries)
