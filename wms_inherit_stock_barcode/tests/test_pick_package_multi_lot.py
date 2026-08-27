"""Unit test PICK dari sale order yang men-scan pallet berisi LEBIH DARI SATU LOT.

Direproduksi dari kejadian nyata **S00163** (DB_WMS_DEV_008):

    picking  FINI/PICK/2094/1601033440 (PICK, uu_only)   <- S00163
    pallet   SPJ-PALLET-0842 (stock.package 7842) di FINI/1601/MUATAN
             +-- stock.quant 8472  lot 246 "22765438 - 25012028"  qty 180
             +-- stock.quant 10347 lot 260 "33965438 - 25012028"  qty 300

Lot 246 sudah dibooking penuh oleh picking lain (FINI/PICK/2126, S00165),
sedangkan yang muncul di suggestion S00163 hanya lot 260. Setelah operator
men-scan pallet-nya, move line 65814 (lot 260) berisi 480 = 300 + 180: qty milik
lot 246 ikut nyangkut di baris lot 260.

Kondisi rusak yang tercatat di DB:

    quant 8472  (lot 246): quantity 180, reserved 180   <- masih milik S00165
    quant 10347 (lot 260): quantity 300, reserved 480   <- kelebihan 180
    stock.move 20251:      demand 17500, quantity 17680 <- kelebihan 180

sehingga validate ditolak dengan "the stock level of the product ... lot 33965438
- 25012028 would become negative (-180.0) on the stock location
'FINI/1601/MUATAN'". Validasi itu benar; yang salah reservasinya.

Aturan yang benar (dari pemilik proses):

    Scan satu pallet = ambil SELURUH isinya, tapi reservasi tiap lot tidak boleh
    melebihi qty lot itu di pallet tersebut. Kalau move line sudah punya
    suggestion pallet + lot, scan menambah qty pada lot tersebut sampai batas qty
    lot itu di pallet, dan kelebihannya masuk ke baris lot lain di pallet yang sama.

Penyebabnya ada di client Barcode: `_processPackage()` memutar tiap quant pallet
lalu mencari line lewat `_findLine()` yang -- pada scan pallet -- tidak membawa
lot, sehingga pencocokan jatuh ke product + package saja dan qty lot A bisa masuk
ke baris lot B. Test di bawah memakai jalur tulis yang persis sama dengan yang
dikirim client (`picking.write({'move_line_ids': ...})`), jadi tidak butuh tour.

Semua test memakai `TransactionCase` -> data uji di-rollback, DB dev tidak berubah.
"""

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'wms_outbound', 'wms_pick_multi_lot')
class TestPickPackageMultiLot(TransactionCase):

    # ------------------------------------------------------------------
    # setup
    # ------------------------------------------------------------------
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = cls.env['res.company'].search([('name', 'like', '1601')], limit=1)
        if not cls.company:
            raise ValueError("Company 1601 (company_id=2) tidak ditemukan di database ini.")

        cls.env.user.write({
            'company_ids': [(4, cls.company.id)],
            'company_id': cls.company.id,
        })
        cls.env = cls.env(context=dict(
            cls.env.context,
            allowed_company_ids=[cls.company.id],
        ))

        cls.type_pick = cls.env['stock.picking.type'].search([
            ('company_id', '=', cls.company.id),
            ('sequence_code', '=', 'PICK'),
            ('uu_only', '=', True),
        ], limit=1)
        if not cls.type_pick:
            raise ValueError("Operation type PICK (uu_only) untuk company %s tidak ada." % cls.company.name)

        cls.loc_stock = cls.type_pick.default_location_src_id
        # Sub-lokasi bin, meniru FINI/1601/MUATAN.
        cls.loc_bin = cls.env['stock.location'].create({
            'name': 'UT-MUATAN',
            'location_id': cls.loc_stock.id,
            'usage': 'internal',
            'company_id': cls.company.id,
        })

        reference = cls.env['product.product'].search([
            ('uom_bag_id', '!=', False),
            ('uom_pallet_id', '!=', False),
            ('tracking', '=', 'lot'),
        ], limit=1)
        if not reference:
            raise ValueError("Tidak ada produk dengan UoM Bag & Pallet untuk dijadikan acuan.")

        cls.product = cls.env['product.product'].create({
            'name': 'UT Fresh Pack Multi Lot',
            'default_code': 'UT-C.BLP80TNSP',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'lot',
            'uom_id': reference.uom_id.id,
            'uom_bag_id': reference.uom_bag_id.id,
            'uom_pallet_id': reference.uom_pallet_id.id,
        })

        # Dua lot dalam satu pallet, persis seperti pallet 7842.
        cls.lot_a = cls.env['stock.lot'].create({
            'name': 'UT-22765438 - 25012028',
            'product_id': cls.product.id,
            'company_id': cls.company.id,
        })
        cls.lot_b = cls.env['stock.lot'].create({
            'name': 'UT-33965438 - 25012028',
            'product_id': cls.product.id,
            'company_id': cls.company.id,
        })

        cls.qty_lot_a = 180.0   # quant 8472
        cls.qty_lot_b = 300.0   # quant 10347

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _make_pallet(self, name='UT-SPJ-PALLET-0842'):
        package = self.env['stock.package'].create({
            'name': name,
            'company_id': self.company.id,
        })
        package.yellow_tag = 'ready'
        return package

    def _add_quant(self, package, lot, qty, location=None):
        """Isi pallet dengan satu lot. Urutan pemanggilan = urutan FIFO."""
        location = location or self.loc_bin
        self.env['stock.quant']._update_available_quantity(
            self.product, location, qty, lot_id=lot, package_id=package,
        )
        quant = self.env['stock.quant'].sudo().search([
            ('product_id', '=', self.product.id),
            ('location_id', '=', location.id),
            ('lot_id', '=', lot.id),
            ('package_id', '=', package.id),
        ], limit=1)
        quant.write({'stock_type': 'UU'})
        return quant

    def _make_pick(self, qty):
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.type_pick.id,
            'location_id': self.loc_stock.id,
            'location_dest_id': self.type_pick.default_location_dest_id.id,
            'company_id': self.company.id,
        })
        self.env['stock.move'].create({
            'picking_id': picking.id,
            'product_id': self.product.id,
            'product_uom_qty': qty,
            'product_uom': self.product.uom_id.id,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
            'company_id': self.company.id,
            'procure_method': 'make_to_stock',
        })
        picking.action_confirm()
        return picking

    def _setup_s00163(self):
        """Kondisi awal persis S00163 vs S00165 di pallet yang sama."""
        pallet = self._make_pallet()
        quant_a = self._add_quant(pallet, self.lot_a, self.qty_lot_a)
        quant_b = self._add_quant(pallet, self.lot_b, self.qty_lot_b)

        # S00165 lebih dulu membooking seluruh lot A.
        other_pick = self._make_pick(self.qty_lot_a)
        other_pick.action_assign()

        # S00163 hanya kebagian lot B.
        pick = self._make_pick(self.qty_lot_b)
        pick.action_assign()

        return pallet, quant_a, quant_b, other_pick, pick

    def _scan_whole_pallet(self, picking, line, qty, context=None):
        """Tiru simpanan client Barcode: satu perintah write ke move_line_ids."""
        picking = picking.with_context(**(context or {}))
        picking.write({'move_line_ids': [(1, line.id, {
            'quantity': qty,
            'picked': True,
        })]})
        self.env.flush_all()

    # ------------------------------------------------------------------
    # 1. Kondisi awal: tiap lot punya barisnya sendiri
    # ------------------------------------------------------------------
    def test_01_reservasi_awal_terpisah_per_lot(self):
        """Sebelum di-scan, reservasi tiap quant harus sama dengan qty line-nya."""
        pallet, quant_a, quant_b, other_pick, pick = self._setup_s00163()

        line_other = other_pick.move_line_ids
        line_pick = pick.move_line_ids
        self.assertEqual(len(line_other), 1)
        self.assertEqual(len(line_pick), 1)
        self.assertEqual(line_other.lot_id, self.lot_a, "Picking pertama harus memegang lot A.")
        self.assertEqual(line_pick.lot_id, self.lot_b, "Lot A sudah habis dibooking, S00163 harus dapat lot B.")
        self.assertEqual(line_other.package_id, pallet)
        self.assertEqual(line_pick.package_id, pallet)

        self.assertEqual(quant_a.reserved_quantity, self.qty_lot_a)
        self.assertEqual(quant_b.reserved_quantity, self.qty_lot_b)
        self.assertEqual(quant_a.available_quantity, 0.0)
        self.assertEqual(quant_b.available_quantity, 0.0)

    # ------------------------------------------------------------------
    # 2. Reproduksi bug S00163
    # ------------------------------------------------------------------
    def test_02_scan_pallet_membagi_qty_ke_baris_lot_masing_masing(self):
        """Scan pallet mengambil seluruh isinya, tiap lot dengan qty lot-nya sendiri.

        Inilah tulisan yang dikirim client setelah scan pallet: satu baris lot B
        dengan qty 480 = isi seluruh pallet (bug S00163). Yang benar: 300 tetap di
        baris lot B, 180 sisanya pindah ke baris lot A.
        """
        pallet, quant_a, quant_b, other_pick, pick = self._setup_s00163()
        line_pick = pick.move_line_ids

        self._scan_whole_pallet(pick, line_pick, self.qty_lot_a + self.qty_lot_b)

        lines = pick.move_line_ids
        self.assertEqual(len(lines), 2, "Kelebihan qty harus jadi baris lot-nya sendiri.")
        qty_by_lot = {line.lot_id: line.quantity for line in lines}
        self.assertEqual(
            qty_by_lot,
            {self.lot_b: self.qty_lot_b, self.lot_a: self.qty_lot_a},
            "Tiap lot harus dapat persis qty lot itu di pallet.",
        )
        self.assertEqual(
            sum(lines.mapped('quantity')), self.qty_lot_a + self.qty_lot_b,
            "Seluruh isi pallet tetap terambil.",
        )
        self.assertEqual(set(lines.mapped('package_id')), {pallet})
        self.assertTrue(all(lines.mapped('picked')))

        # Reservasi per baris tidak melebihi qty lot di pallet.
        for line in lines:
            quant = quant_a if line.lot_id == self.lot_a else quant_b
            self.assertLessEqual(line.quantity, quant.quantity)

        # Konsekuensi yang perlu disadari: lot A kini dipegang dua dokumen
        # sekaligus (180 + 180 pada quant berisi 180). Core melepas reservasi
        # dokumen yang kalah cepat lewat _free_reservation() saat validate --
        # lihat test_07.
        self.assertEqual(quant_b.reserved_quantity, self.qty_lot_b)
        self.assertEqual(quant_a.reserved_quantity, self.qty_lot_a * 2)

    def test_03_qty_melebihi_isi_pallet_ditolak(self):
        """Yang tidak muat di lot mana pun di pallet tetap ditolak."""
        pallet, quant_a, quant_b, other_pick, pick = self._setup_s00163()
        line_pick = pick.move_line_ids

        # Persis sebesar isi lot B: sah, tidak ada yang perlu dipindah.
        self._scan_whole_pallet(pick, line_pick, self.qty_lot_b)
        self.assertEqual(len(pick.move_line_ids), 1)
        self.assertEqual(line_pick.quantity, self.qty_lot_b)
        self.assertEqual(quant_b.reserved_quantity, self.qty_lot_b)

        # Lebih besar dari SELURUH isi pallet: ditolak.
        with self.assertRaises(ValidationError) as err:
            with self.env.cr.savepoint():
                self._scan_whole_pallet(
                    pick, line_pick, self.qty_lot_a + self.qty_lot_b + 1,
                )
        message = str(err.exception)
        self.assertIn(pallet.name, message, "Pesan error harus menyebut pallet yang di-scan.")
        self.assertIn(self.lot_b.name, message, "Pesan error harus menyebut lot yang kelebihan.")

    # ------------------------------------------------------------------
    # 3. Rantai sebab-akibat: reservasi rusak -> stok negatif saat validate
    # ------------------------------------------------------------------
    def test_04_tanpa_guard_reservasi_rusak_seperti_di_database(self):
        """Dengan guard dimatikan, hasilnya persis quant 8472 & 10347 di DB."""
        pallet, quant_a, quant_b, other_pick, pick = self._setup_s00163()
        line_pick = pick.move_line_ids

        self._scan_whole_pallet(
            pick, line_pick, self.qty_lot_a + self.qty_lot_b,
            context={
                'skip_pallet_lot_spread': True,
                'skip_package_lot_capacity_check': True,
            },
        )

        self.assertEqual(quant_a.quantity, self.qty_lot_a)
        self.assertEqual(quant_a.reserved_quantity, self.qty_lot_a)
        self.assertEqual(
            quant_b.quantity, self.qty_lot_b,
            "Isi fisik lot B tetap 300 -- yang berubah cuma reservasinya.",
        )
        self.assertEqual(
            quant_b.reserved_quantity, self.qty_lot_a + self.qty_lot_b,
            "Reservasi lot B jadi 480 seperti quant 10347 di DB.",
        )
        self.assertEqual(
            quant_b.available_quantity, -self.qty_lot_a,
            "Available quant lot B jadi -180 -- inilah sumber error stok negatif "
            "saat button_validate.",
        )
        self.assertEqual(
            pick.move_ids.quantity, self.qty_lot_a + self.qty_lot_b,
            "Move ikut kelebihan 180 dari demand-nya (17680 vs 17500 di S00163).",
        )

    # ------------------------------------------------------------------
    # 4. Jalur sehat: pallet dua lot yang dua-duanya bebas
    # ------------------------------------------------------------------
    def test_05_pallet_dua_lot_bebas_direservasi_per_lot(self):
        """Tanpa booking dokumen lain, satu pallet dua lot -> dua move line."""
        pallet = self._make_pallet('UT-SPJ-PALLET-BEBAS')
        quant_a = self._add_quant(pallet, self.lot_a, self.qty_lot_a)
        quant_b = self._add_quant(pallet, self.lot_b, self.qty_lot_b)

        pick = self._make_pick(self.qty_lot_a + self.qty_lot_b)
        pick.action_assign()

        lines = pick.move_line_ids
        self.assertEqual(len(lines), 2, "Tiap lot di pallet harus punya move line sendiri.")
        qty_by_lot = {line.lot_id: line.quantity for line in lines}
        self.assertEqual(qty_by_lot[self.lot_a], self.qty_lot_a)
        self.assertEqual(qty_by_lot[self.lot_b], self.qty_lot_b)
        self.assertEqual(quant_a.reserved_quantity, self.qty_lot_a)
        self.assertEqual(quant_b.reserved_quantity, self.qty_lot_b)

    def test_06_validate_pallet_penuh_dua_lot(self):
        """Reservasi per lot yang benar -> PICK bisa divalidasi tanpa stok negatif."""
        pallet = self._make_pallet('UT-SPJ-PALLET-BEBAS')
        quant_a = self._add_quant(pallet, self.lot_a, self.qty_lot_a)
        quant_b = self._add_quant(pallet, self.lot_b, self.qty_lot_b)

        pick = self._make_pick(self.qty_lot_a + self.qty_lot_b)
        pick.action_assign()
        pick.move_line_ids.write({'picked': True})

        res = pick.with_context(test_stock_no_negative=True).button_validate()
        self.assertNotIsInstance(res, dict, "button_validate %s minta wizard: %s" % (pick.name, res))
        self.assertEqual(pick.state, 'done')

        self.env.invalidate_all()
        self.assertFalse(quant_a.exists() and quant_a.quantity)
        self.assertFalse(quant_b.exists() and quant_b.quantity)

        moved = self.env['stock.quant'].sudo().search([
            ('product_id', '=', self.product.id),
            ('package_id', '=', pallet.id),
            ('location_id', '=', self.type_pick.default_location_dest_id.id),
        ])
        self.assertEqual(
            {q.lot_id: q.quantity for q in moved},
            {self.lot_a: self.qty_lot_a, self.lot_b: self.qty_lot_b},
            "Kedua lot harus pindah utuh dengan qty masing-masing.",
        )

    def test_09_repair_baris_lama_yang_sudah_terlanjur_rusak(self):
        """Baris yang rusak SEBELUM fix ini ada tidak sembuh sendiri saat validate.

        `_spread_pallet_lot_excess()` cuma jalan saat `quantity` ditulis, sedangkan
        validate menulis `state`. Jadi record lama seperti move line 65814 di
        S00163 harus diperbaiki lewat `_repair_pallet_lot_overbooking()`.
        """
        pallet, quant_a, quant_b, other_pick, pick = self._setup_s00163()
        line_pick = pick.move_line_ids

        # Kondisi warisan: 480 pada baris lot B, tanpa pemecahan.
        self._scan_whole_pallet(
            pick, line_pick, self.qty_lot_a + self.qty_lot_b,
            context={
                'skip_pallet_lot_spread': True,
                'skip_package_lot_capacity_check': True,
            },
        )
        self.assertEqual(len(pick.move_line_ids), 1)
        self.assertEqual(line_pick.quantity, self.qty_lot_a + self.qty_lot_b)

        # dry_run: melaporkan, tidak mengubah apa pun.
        laporan = self.env['stock.move.line']._repair_pallet_lot_overbooking(
            picking_ids=pick.ids,
        )
        self.assertEqual(len(laporan['ditemukan']), 1)
        self.assertFalse(laporan['diperbaiki'])
        self.assertEqual(line_pick.quantity, self.qty_lot_a + self.qty_lot_b)

        # eksekusi.
        laporan = self.env['stock.move.line']._repair_pallet_lot_overbooking(
            picking_ids=pick.ids, dry_run=False,
        )
        self.assertEqual(len(laporan['diperbaiki']), 1, laporan)
        self.assertFalse(laporan['perlu_keputusan'], laporan)

        lines = pick.move_line_ids
        self.assertEqual(
            {line.lot_id: line.quantity for line in lines},
            {self.lot_b: self.qty_lot_b, self.lot_a: self.qty_lot_a},
            "Repair harus memecah 480 jadi 300 lot B + 180 lot A.",
        )
        self.assertEqual(quant_b.reserved_quantity, self.qty_lot_b)

    def test_10_repair_tidak_menyentuh_baris_yang_tidak_bisa_dibetulkan(self):
        """Kalau kelebihannya tidak muat di lot mana pun, baris dibiarkan utuh.

        Menulis ulang qty yang sama tidak memperbaiki apa pun, tapi tetap memicu
        siklus unreserve/reserve di stock.quant -- dan kalau quant-nya sedang
        terkunci sesi lain, core membuat baris quant duplikat.
        """
        pallet = self._make_pallet('UT-SPJ-PALLET-SATU-LOT')
        self._add_quant(pallet, self.lot_a, self.qty_lot_a)

        pick = self._make_pick(self.qty_lot_a)
        pick.action_assign()
        line = pick.move_line_ids
        self.assertEqual(len(line), 1)

        # Kondisi warisan: qty melebihi isi pallet, tanpa lot lain untuk menampung.
        self._scan_whole_pallet(
            pick, line, self.qty_lot_a + 120.0,
            context={
                'skip_pallet_lot_spread': True,
                'skip_package_lot_capacity_check': True,
            },
        )
        qty_sebelum = line.quantity
        write_date_sebelum = line.write_date

        laporan = self.env['stock.move.line']._repair_pallet_lot_overbooking(
            picking_ids=pick.ids, dry_run=False,
        )
        self.assertEqual(len(laporan['perlu_keputusan']), 1, laporan)
        self.assertFalse(laporan['diperbaiki'], laporan)
        self.assertEqual(len(pick.move_line_ids), 1, "Tidak boleh ada baris baru.")
        self.assertEqual(line.quantity, qty_sebelum, "Qty baris tidak boleh berubah.")
        self.assertEqual(line.write_date, write_date_sebelum, "Baris tidak boleh disentuh.")

    # ------------------------------------------------------------------
    # 5. Kasus S00163 utuh: scan pallet -> validate
    # ------------------------------------------------------------------
    def test_07_scan_pallet_s00163_bisa_divalidasi(self):
        """Setelah pembagian per lot benar, seluruh pallet keluar dan validate lolos.

        Konsekuensinya: reservasi dokumen lain atas lot A dilepas core lewat
        `_free_reservation()` karena palletnya memang sudah keluar gudang.
        """
        pallet, quant_a, quant_b, other_pick, pick = self._setup_s00163()
        line_other = other_pick.move_line_ids
        line_pick = pick.move_line_ids

        self._scan_whole_pallet(pick, line_pick, self.qty_lot_a + self.qty_lot_b)

        res = pick.with_context(test_stock_no_negative=True).button_validate()
        self.assertNotIsInstance(res, dict, "button_validate %s minta wizard: %s" % (pick.name, res))
        self.assertEqual(pick.state, 'done')

        self.env.invalidate_all()
        moved = self.env['stock.quant'].sudo().search([
            ('product_id', '=', self.product.id),
            ('package_id', '=', pallet.id),
            ('location_id', '=', self.type_pick.default_location_dest_id.id),
        ])
        self.assertEqual(
            {q.lot_id: q.quantity for q in moved},
            {self.lot_a: self.qty_lot_a, self.lot_b: self.qty_lot_b},
            "Seluruh isi pallet harus pindah ke STG - OUT dengan qty per lot utuh.",
        )
        self.assertFalse(
            self.env['stock.quant'].sudo().search([
                ('package_id', '=', pallet.id),
                ('location_id', '=', self.loc_bin.id),
                ('quantity', '>', 0),
            ]),
            "Tidak boleh ada isi pallet yang tertinggal di lokasi asal.",
        )
        self.assertFalse(
            line_other.exists() and line_other.quantity,
            "Reservasi picking lain atas lot A dilepas karena palletnya sudah keluar.",
        )

    def test_08_pallet_tidak_boleh_dibelah_ke_dua_lokasi(self):
        """Alasan kenapa scan pallet harus mengambil SELURUH isinya.

        Kalau hanya lot B yang diambil, core `stock.move._action_done()` menolak
        karena pallet yang sama akan berakhir di dua lokasi: lot A tertinggal di
        MUATAN, lot B sudah di STG - OUT.
        """
        pallet, quant_a, quant_b, other_pick, pick = self._setup_s00163()
        line_pick = pick.move_line_ids

        self._scan_whole_pallet(pick, line_pick, self.qty_lot_b)

        with self.assertRaises(UserError) as err:
            with self.env.cr.savepoint():
                pick.with_context(test_stock_no_negative=True).button_validate()
        self.assertIn('package', str(err.exception).lower())
