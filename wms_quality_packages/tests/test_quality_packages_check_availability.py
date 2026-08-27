"""Unit test `quality.packages.check_availability()`.

Menutup enam cacat yang ditemukan pada versi sebelumnya:

1. quant bersaldo 0 ikut jadi baris detail (tidak ada filter `quantity > 0`);
2. filter `date_done` membandingkan tanggal lokal user dengan kolom UTC, jadi
   jendelanya bergeser 7 jam di WIB;
3. filter shift / tanggal / line dilakukan lewat `lot_id`, sehingga satu lot yang
   diproduksi lintas shift menarik SELURUH stoknya, bukan hanya pallet dari shift
   yang dipilih;
4. detail lama dihapus SEBELUM pencarian, jadi pencarian yang nihil ikut
   memusnahkan data yang sudah ada;
5. `is_checked` bisa jadi True tanpa satu baris pun terbentuk;
6. `lot_stock_id` (turunan warehouse) mempersempit pencarian ke lokasi stok utama,
   sehingga pallet QI yang masih di staging tidak pernah terlihat.

Test terakhir menjalankan skenario yang diminta: warehouse 3 (1481 - FINI),
production line 26 (CPP PLANT 1 LINE 45), action AFT 7 (QI to UU) di atas data
DB_WMS_DEV_008 yang sebenarnya.

Jalankan:
    D:\\CPP\\Odoo19-ENT\\python\\python.exe odoo-bin -c wms.conf \\
        -u wms_quality_packages --test-enable --test-tags wms_quality_pkg \\
        --stop-after-init --no-http
"""

import logging
from datetime import date, datetime

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install', 'wms_quality_pkg')
class TestQualityPackagesCheckAvailability(TransactionCase):

    # ------------------------------------------------------------------
    # setup
    # ------------------------------------------------------------------
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Warehouse 3 = "1481 - FINI" (company 3). Semua test memakai warehouse
        # ini supaya skenario yang diminta user dan skenario sintetis berjalan
        # di atas konfigurasi routing yang sama.
        cls.warehouse = cls.env['stock.warehouse'].browse(3).exists()
        if not cls.warehouse:
            raise ValueError("Butuh stock.warehouse id 3 (1481 - FINI)")
        cls.company = cls.warehouse.company_id
        cls.lot_stock = cls.warehouse.lot_stock_id

        # Timezone user menentukan batas hari untuk filter `date_done`.
        cls.env.user.tz = 'Asia/Jakarta'

        cls.in_type = cls.env['stock.picking.type'].search(
            [
                ('warehouse_id', '=', cls.warehouse.id),
                ('code', '=', 'incoming'),
                ('name', 'ilike', 'Inbound FG Production'),
            ],
            limit=1,
        ) or cls.env['stock.picking.type'].search(
            [('warehouse_id', '=', cls.warehouse.id), ('code', '=', 'incoming')],
            limit=1,
        )
        if not cls.in_type:
            raise ValueError("Butuh operation type incoming pada warehouse 3")

        cls.supplier_loc = cls.env.ref('stock.stock_location_suppliers')

        # Lokasi internal warehouse 3 yang BUKAN turunan lot_stock -- inilah
        # staging (FINI/STG - IN) yang hilang gara-gara filter lot_stock_id.
        cls.staging_loc = cls.env['stock.location'].search(
            [
                ('warehouse_id', '=', cls.warehouse.id),
                ('usage', '=', 'internal'),
                '!', ('id', 'child_of', cls.lot_stock.id),
            ],
            limit=1,
        )

        cls.product = cls.env['product.product'].search(
            [
                ('is_storable', '=', True),
                ('tracking', '=', 'lot'),
                ('uom_bag_id', '!=', False),
            ],
            limit=1,
        )
        if not cls.product:
            raise ValueError("Butuh produk storable dengan tracking lot dan uom_bag_id")

        cls.line_a, cls.line_b = cls.env['production.line'].create([
            {'name': 'UT LINE A', 'company_id': cls.company.id},
            {'name': 'UT LINE B', 'company_id': cls.company.id},
        ])
        cls.shift_a, cls.shift_b = cls.env['production.shift'].create([
            {'name': 'UT SHIFT A', 'company_id': cls.company.id},
            {'name': 'UT SHIFT B', 'company_id': cls.company.id},
        ])
        cls.aft_qi_uu = cls.env['sap.aft'].create({
            'name': 'UT QI to UU',
            'stock_type_from': 'QI',
            'stock_type_to': 'UU',
            'move_type': '321',
        })

        # Operation type "Inbound FG Production" ber-`production_only`, jadi
        # picking-nya wajib punya PO SAP sebelum boleh di-confirm.
        cls.po_sap = cls.env['production.order.sap'].create({
            'po_number': 'UT-PO-QP-001',
            'product_id': cls.product.id,
            'uom_id': cls.product.uom_id.id,
            'order_qty': 100000.0,
            'company_id': cls.company.id,
            'state': 'open',
        })

        cls.lot_shared = cls.env['stock.lot'].create({
            'name': 'UT-LOT-SHARED',
            'product_id': cls.product.id,
            'company_id': cls.company.id,
        })

    # ------------------------------------------------------------------
    # helper
    # ------------------------------------------------------------------
    def _receive(self, package_name, qty=100.0, lot=None, dest=None,
                 shift=None, prod_line=None, done_date=None, stock_type='QI'):
        """Terima satu pallet hasil produksi, kembalikan quant-nya.

        Meniru alur nyata: picking `incoming` (Inbound FG Production) dengan
        `production_shift_id` pada picking dan `result_package_id` pada move
        line -- persis bentuk data yang dibaca `_get_produced_stock_keys()`.
        """
        lot = lot or self.lot_shared
        dest = dest or self.lot_stock
        package = self.env['stock.package'].create({
            'name': package_name,
            'company_id': self.company.id,
        })
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.in_type.id,
            'location_id': self.supplier_loc.id,
            'location_dest_id': dest.id,
            'company_id': self.company.id,
            'production_shift_id': shift.id if shift else False,
            'po_sap_id': self.po_sap.id,
        })
        move = self.env['stock.move'].create({
            'picking_id': picking.id,
            'product_id': self.product.id,
            'product_uom_qty': qty,
            'product_uom': self.product.uom_id.id,
            'location_id': self.supplier_loc.id,
            'location_dest_id': dest.id,
            'company_id': self.company.id,
        })
        picking.action_confirm()
        move.move_line_ids.unlink()
        self.env['stock.move.line'].create({
            'move_id': move.id,
            'picking_id': picking.id,
            'product_id': self.product.id,
            'product_uom_id': self.product.uom_id.id,
            'quantity': qty,
            'lot_id': lot.id,
            'result_package_id': package.id,
            'location_id': self.supplier_loc.id,
            'location_dest_id': dest.id,
            'company_id': self.company.id,
        })
        move.picked = True
        picking._action_done()

        if done_date:
            picking.move_line_ids.write({'date': done_date})

        quant = self.env['stock.quant'].sudo().search([
            ('package_id', '=', package.id),
            ('quantity', '!=', 0),
        ])
        self.assertEqual(len(quant), 1, "Penerimaan harus menghasilkan tepat 1 quant")
        quant.write({
            'stock_type': stock_type,
            'production_line_id': prod_line.id if prod_line else False,
        })
        return quant

    def _new_qp(self, **vals):
        base = {
            'company_id': self.company.id,
            'warehouse_id': self.warehouse.id,
            'lot_stock_id': self.lot_stock.id,
            'action_aft_id': self.aft_qi_uu.id,
        }
        base.update(vals)
        return self.env['quality.packages'].create(base)

    # ------------------------------------------------------------------
    # 1. quant bersaldo 0
    # ------------------------------------------------------------------
    def test_01_zero_quantity_quant_excluded(self):
        keep = self._receive('UT-PLT-KEEP', prod_line=self.line_a)
        empty = self._receive('UT-PLT-EMPTY', prod_line=self.line_a)
        empty.write({'quantity': 0.0})

        qp = self._new_qp(production_line_id=self.line_a.id)
        qp.check_availability()

        self.assertEqual(qp.quality_line_ids.quant_id, keep)
        self.assertTrue(qp.is_checked)

    # ------------------------------------------------------------------
    # 2. production line dibaca dari quant, bukan dari lot
    # ------------------------------------------------------------------
    def test_02_production_line_filter_is_per_quant(self):
        """Dua pallet LOT YANG SAMA dari line berbeda: hanya line terpilih ikut.

        Ini kasus yang dulu salah -- filter lewat `lot_id` menarik kedua pallet
        karena lot-nya memang sama.
        """
        on_line_a = self._receive('UT-PLT-LINE-A', prod_line=self.line_a)
        self._receive('UT-PLT-LINE-B', prod_line=self.line_b)

        qp = self._new_qp(production_line_id=self.line_a.id)
        qp.check_availability()

        self.assertEqual(qp.quality_line_ids.quant_id, on_line_a)
        self.assertEqual(qp.quality_line_ids.production_line_id, self.line_a)

    # ------------------------------------------------------------------
    # 3. shift dibaca per pallet, bukan per lot
    # ------------------------------------------------------------------
    def test_03_shift_filter_is_per_pallet(self):
        on_shift_a = self._receive('UT-PLT-SHIFT-A', shift=self.shift_a)
        self._receive('UT-PLT-SHIFT-B', shift=self.shift_b)

        qp = self._new_qp(production_shift_id=self.shift_a.id)
        qp.check_availability()

        self.assertEqual(qp.quality_line_ids.quant_id, on_shift_a)

    def test_04_shift_filter_ignores_non_production_moves(self):
        """Pallet yang cuma DIPINDAH pada shift itu bukan 'diproduksi' di sana."""
        produced = self._receive('UT-PLT-PROD-A', shift=self.shift_a)
        moved = self._receive('UT-PLT-PROD-B', shift=self.shift_b)

        # Pindahan internal di shift A: tidak boleh membuat `moved` terjaring.
        internal_type = self.env['stock.picking.type'].search(
            [('warehouse_id', '=', self.warehouse.id), ('code', '=', 'internal')],
            limit=1,
        )
        picking = self.env['stock.picking'].create({
            'picking_type_id': internal_type.id,
            'location_id': moved.location_id.id,
            'location_dest_id': moved.location_id.id,
            'company_id': self.company.id,
            'production_shift_id': self.shift_a.id,
        })
        self.env['stock.move'].create({
            'picking_id': picking.id,
            'product_id': self.product.id,
            'product_uom_qty': moved.quantity,
            'product_uom': self.product.uom_id.id,
            'location_id': moved.location_id.id,
            'location_dest_id': moved.location_id.id,
            'company_id': self.company.id,
        })
        picking.action_confirm()

        qp = self._new_qp(production_shift_id=self.shift_a.id)
        qp.check_availability()

        self.assertEqual(qp.quality_line_ids.quant_id, produced)

    # ------------------------------------------------------------------
    # 5. batas hari `date_done` mengikuti timezone user
    # ------------------------------------------------------------------
    def test_05_date_done_uses_user_timezone(self):
        """Produksi 20 Agu 01:30 WIB tersimpan sebagai 19 Agu 18:30 UTC.

        Versi lama membandingkannya sebagai UTC, jadi pallet ini muncul saat
        user memilih 19 Agustus dan hilang saat memilih 20 Agustus -- terbalik.
        """
        # Lot khusus supaya stok nyata yang kebetulan diproduksi pada tanggal
        # yang sama tidak ikut terjaring dan mengaburkan yang diuji.
        lot = self.env['stock.lot'].create({
            'name': 'UT-LOT-TZ',
            'product_id': self.product.id,
            'company_id': self.company.id,
        })
        quant = self._receive(
            'UT-PLT-TZ',
            lot=lot,
            done_date=datetime(2026, 8, 19, 18, 30, 0),  # = 2026-08-20 01:30 WIB
        )

        qp_correct = self._new_qp(lot_id=lot.id, date_done=date(2026, 8, 20))
        qp_correct.check_availability()
        self.assertEqual(qp_correct.quality_line_ids.quant_id, quant)

        qp_wrong = self._new_qp(lot_id=lot.id, date_done=date(2026, 8, 19))
        with self.assertRaises(ValidationError):
            qp_wrong.check_availability()

    # ------------------------------------------------------------------
    # 6. pencarian nihil tidak boleh merusak detail yang sudah ada
    # ------------------------------------------------------------------
    def test_06_empty_result_keeps_existing_lines(self):
        self._receive('UT-PLT-EXIST', prod_line=self.line_a)

        qp = self._new_qp(production_line_id=self.line_a.id)
        qp.check_availability()
        existing = qp.quality_line_ids
        self.assertTrue(existing)

        # Kriteria yang pasti nihil.
        qp.production_line_id = self.line_b
        with self.assertRaises(ValidationError):
            qp.check_availability()

        self.assertEqual(qp.quality_line_ids, existing, "Detail lama tidak boleh hilang")

    # ------------------------------------------------------------------
    # 7. is_checked hanya True kalau detail benar-benar terbentuk
    # ------------------------------------------------------------------
    def test_07_is_checked_only_with_lines(self):
        qp = self._new_qp(production_line_id=self.line_b.id)
        with self.assertRaises(ValidationError):
            qp.check_availability()
        self.assertFalse(qp.is_checked)
        self.assertFalse(qp.quality_line_ids)

    # ------------------------------------------------------------------
    # 8. staging tidak boleh hilang gara-gara lot_stock_id
    # ------------------------------------------------------------------
    def test_08_warehouse_filter_includes_staging(self):
        if not self.staging_loc:
            self.skipTest("Warehouse 3 tidak punya lokasi internal di luar lot_stock")

        in_stock = self._receive('UT-PLT-STOCK', prod_line=self.line_a)
        in_staging = self._receive(
            'UT-PLT-STAGING', prod_line=self.line_a, dest=self.staging_loc,
        )

        qp = self._new_qp(production_line_id=self.line_a.id)
        qp.check_availability()

        self.assertEqual(qp.quality_line_ids.quant_id, in_stock | in_staging)

    # ------------------------------------------------------------------
    # 9. skenario yang diminta: warehouse 3 / line 26 / AFT 7, data nyata
    # ------------------------------------------------------------------
    def test_09_scenario_warehouse3_line26_aft7(self):
        prod_line = self.env['production.line'].browse(26).exists()
        aft = self.env['sap.aft'].browse(7).exists()
        if not prod_line or not aft:
            self.skipTest("Butuh production.line 26 dan sap.aft 7 di database ini")
        self.assertEqual(aft.stock_type_from, 'QI')
        self.assertEqual(aft.stock_type_to, 'UU')

        # Rumusan independen dari domain yang dipakai kode (child_of view
        # location, bukan field warehouse_id) supaya benar-benar jadi pembanding.
        expected = self.env['stock.quant'].sudo().search([
            ('company_id', '=', self.company.id),
            ('location_id', 'child_of', self.warehouse.view_location_id.id),
            ('location_id.usage', '=', 'internal'),
            ('stock_type', '=', 'QI'),
            ('production_line_id', '=', prod_line.id),
            ('quantity', '>', 0),
        ])
        if not expected:
            self.skipTest("Tidak ada stok QI line 26 di warehouse 3 pada database ini")

        qp = self._new_qp(
            production_line_id=prod_line.id,
            action_aft_id=aft.id,
        )
        qp.check_availability()

        _logger.info(
            "Skenario WH %s / line %s / AFT %s -> %s pallet: %s",
            self.warehouse.name, prod_line.name, aft.name,
            len(qp.quality_line_ids), qp.quality_line_ids.quant_id.ids,
        )
        self.assertTrue(qp.is_checked)
        self.assertEqual(qp.quality_line_ids.quant_id, expected)
        for line in qp.quality_line_ids:
            self.assertGreater(line.quantity, 0.0)
            self.assertEqual(line.quant_id.stock_type, 'QI')
            self.assertEqual(line.production_line_id, prod_line)
            self.assertTrue(line.lot_id)
