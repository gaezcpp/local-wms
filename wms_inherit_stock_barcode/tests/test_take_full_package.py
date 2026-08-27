"""Unit test: scan pallet harus mengambil SELURUH isi pallet.

Dua kejadian nyata di DB_WMS_DEV_008 yang bentuk kerusakannya berbeda, tapi
akarnya sama -- pembagian qty hasil scan pallet ditentukan client, dan
`_processPackage()` core mencocokkan quant ke baris lewat `_findLine()` yang pada
scan pallet TIDAK membawa lot:

**S00764 / FINI/PICK/26/6356/1608953947 -- SPJ-PALLET-10425 (isi 1.280)**

    lot 160110003515|95      200
    lot 23765636 - 12022028  740   <- hanya 640 yang terambil (angka reservasi)
    lot 32765636 - 12022028   40
    lot 160110003515|71      300
                           ------
    terambil                1.180  (kurang 100)

**S00790 / FINI/PICK/26/6492/wertyui -- SPJ-PALLET-10024 (isi 1.280)**

    lot C.CH20TNSP SO 02 Agustus 2026  620
    lot 22865533 - 30012028             80
    lot 21865538 - 04022028            160   <- TIDAK dapat baris sama sekali
    lot 33865538 - 04022028            420
                                     ------
    terambil                          1.120  (kurang 160)

Kasus kedua lebih parah: satu lot tidak kebagian baris sama sekali. Pemicunya
`_lineCannotBeTaken()` core --

    const fullyPacked = line.result_package_id &&
        (!line.reserved_uom_qty || this._lineIsComplete(line));

-- di picking `UU Only` SEMUA baris punya `result_package_id` (dipasang
`stock.move._autofill_result_package()`), jadi baris yang sudah penuh ATAU baris
bentukan client (reservasi 0) langsung dianggap "fully packed" dan tidak boleh
diisi lagi. Isi pallet yang belum kebagian karena itu bisa hilang begitu saja.

Keduanya berujung sama saat Validate: pallet pecah -> quant pallet yang sama ada
di dua lokasi -> core menolak dengan "You cannot move the same package content
more than once in the same transfer or split the same package into two location."

`stock.picking._take_full_package()` menutup celah itu di SERVER: qty tiap
(product, lot) dihitung ulang dari quant pallet, bukan dari hasil tebakan client.

Jalankan:
    python odoo-bin -c wms.conf -u wms_inherit_stock_barcode --test-enable \\
        --test-tags wms_full_package --stop-after-init --no-http
"""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'wms_full_package')
class TestTakeFullPackage(TransactionCase):

    # ------------------------------------------------------------------
    # setup
    # ------------------------------------------------------------------
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = cls.env.company
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1
        )
        if not cls.warehouse:
            raise ValueError("Butuh minimal satu warehouse untuk company %s" % cls.company.name)

        icp = cls.env['ir.config_parameter'].sudo()
        if not icp.get_param('prod_in_move_type'):
            icp.set_param('prod_in_move_type', '101')
        icp.set_param('upload_stock', 'false')

        Location = cls.env['stock.location']
        cls.loc_src = Location.create({
            'name': 'UT-FP-MUATAN',
            'location_id': cls.warehouse.lot_stock_id.id,
            'usage': 'internal',
            'company_id': cls.company.id,
        })
        cls.loc_dest = Location.create({
            'name': 'UT-FP-DEST',
            'location_id': cls.warehouse.lot_stock_id.id,
            'usage': 'internal',
            'company_id': cls.company.id,
        })

        cls.product = cls.env['product.product'].create({
            'name': 'UT Full Package Product',
            'default_code': 'UT-FP',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'lot',
        })

        # Isi SPJ-PALLET-10024, urutan sama dengan urutan id quant di DB.
        Lot = cls.env['stock.lot']
        cls.isi = {}
        for name, qty in [
            ('UT-21865538 - 04022028', 160.0),          # quant 68868
            ('UT-C.CH20TNSP SO 02 Agustus 2026', 620.0),  # quant 71228
            ('UT-22865533 - 30012028', 80.0),           # quant 71229
            ('UT-33865538 - 04022028', 420.0),          # quant 71240
        ]:
            lot = Lot.create({
                'name': name,
                'product_id': cls.product.id,
                'company_id': cls.company.id,
            })
            cls.isi[lot] = qty
        cls.lot_hilang = next(lot for lot, qty in cls.isi.items() if qty == 160.0)
        cls.lot_besar = next(lot for lot, qty in cls.isi.items() if qty == 620.0)
        cls.total_isi = sum(cls.isi.values())   # 1280

        cls.type_uu = cls.env['stock.picking.type'].create({
            'name': 'UT FP Pick',
            'sequence_code': 'UTFP',
            'code': 'internal',
            'warehouse_id': cls.warehouse.id,
            'company_id': cls.company.id,
            'default_location_src_id': cls.loc_src.id,
            'default_location_dest_id': cls.loc_dest.id,
            'uu_only': True,
            'split_package': False,
            'book_full_pallet': False,
            'mandatory_destination': False,
        })

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _make_pallet(self, name='UT-SPJ-PALLET-10024'):
        package = self.env['stock.package'].create({
            'name': name,
            'company_id': self.company.id,
        })
        package.yellow_tag = 'ready'
        return package

    def _isi_pallet(self, package, isi=None):
        Quant = self.env['stock.quant']
        for lot, qty in (isi or self.isi).items():
            Quant._update_available_quantity(
                self.product, self.loc_src, qty, lot_id=lot, package_id=package,
            )
        quants = Quant.sudo().search([
            ('product_id', '=', self.product.id),
            ('package_id', '=', package.id),
        ])
        quants.write({'stock_type': 'UU'})
        return quants

    def _make_pick(self, qty, assign=True):
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.type_uu.id,
            'location_id': self.loc_src.id,
            'location_dest_id': self.loc_dest.id,
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
        if assign:
            picking.action_assign()
        return picking

    def _qty_per_lot(self, picking, package):
        hasil = {}
        for line in picking.move_line_ids.filtered(lambda l: l.package_id == package):
            hasil[line.lot_id] = hasil.get(line.lot_id, 0.0) + line.quantity_product_uom
        return {lot: qty for lot, qty in hasil.items() if qty}

    def _total(self, picking, package):
        return sum(self._qty_per_lot(picking, package).values())

    # ==================================================================
    # 1. Reproduksi S00790: satu lot tidak dapat baris sama sekali
    # ==================================================================
    def test_01_lot_yang_tidak_dapat_baris_ditambahkan(self):
        """1.120 dari 1.280 -> `_take_full_package()` membuat baris lot yang hilang."""
        pallet = self._make_pallet()
        self._isi_pallet(pallet)

        pick = self._make_pick(self.total_isi, assign=False)
        # Kondisi persis hasil scan yang rusak: tiga lot terambil penuh, satu lot
        # (160) tidak punya baris sama sekali.
        pick.action_assign()
        pick.move_line_ids.filtered(
            lambda l: l.lot_id == self.lot_hilang
        ).unlink()
        pick.move_line_ids.write({'picked': True})

        self.assertEqual(self._total(pick, pallet), 1120.0, "Kondisi awal harus 1.120.")
        self.assertNotIn(self.lot_hilang, self._qty_per_lot(pick, pallet))

        laporan = pick._take_full_package(pallet)

        self.assertEqual(len(laporan['dibuat']), 1, laporan)
        self.assertFalse(laporan['dilewati'], laporan)
        self.assertEqual(
            self._qty_per_lot(pick, pallet), self.isi,
            "Setiap lot harus terambil persis sebesar isinya di pallet.",
        )
        self.assertEqual(self._total(pick, pallet), self.total_isi)

    def test_02_baris_baru_ikut_picked_dan_membawa_pallet(self):
        """Baris tambahan harus `picked`, kalau tidak ikut dihapus core saat Validate.

        `stock.move._action_done()` menghapus move line yang tidak `picked` dari
        move yang `picked` -- baris tambahan yang lupa ditandai justru membuat
        pallet tetap pecah.
        """
        pallet = self._make_pallet()
        self._isi_pallet(pallet)

        pick = self._make_pick(self.total_isi)
        pick.move_line_ids.filtered(lambda l: l.lot_id == self.lot_hilang).unlink()
        pick.move_line_ids.write({'picked': True})
        pick._take_full_package(pallet)

        baris_baru = pick.move_line_ids.filtered(lambda l: l.lot_id == self.lot_hilang)
        self.assertEqual(len(baris_baru), 1)
        self.assertTrue(baris_baru.picked, "Baris tambahan wajib ikut picked.")
        self.assertEqual(baris_baru.package_id, pallet)
        self.assertEqual(
            baris_baru.result_package_id, pallet,
            "Picking UU membawa pallet-nya, sama seperti baris lain.",
        )
        self.assertEqual(baris_baru.location_id, self.loc_src)

    # ==================================================================
    # 2. Reproduksi S00764: satu lot berhenti di angka reservasinya
    # ==================================================================
    def test_03_lot_yang_kurang_ditambah_sampai_isi_quant(self):
        """1.180 dari 1.280 -> baris lot yang kurang dinaikkan ke isi quant."""
        pallet = self._make_pallet('UT-SPJ-PALLET-10425')
        self._isi_pallet(pallet)

        pick = self._make_pick(self.total_isi)
        baris_kurang = pick.move_line_ids.filtered(lambda l: l.lot_id == self.lot_besar)
        baris_kurang.write({'quantity': self.isi[self.lot_besar] - 100.0})
        pick.move_line_ids.write({'picked': True})

        self.assertEqual(self._total(pick, pallet), self.total_isi - 100.0)

        laporan = pick._take_full_package(pallet)

        self.assertFalse(laporan['dibuat'], laporan)
        self.assertEqual(len(laporan['diubah']), 1, laporan)
        self.assertEqual(self._qty_per_lot(pick, pallet), self.isi)

    def test_04_kelebihan_qty_dipotong_kembali(self):
        """Arah sebaliknya: lot yang kelebihan dipotong sampai isi quant.

        Ini yang membuat hasilnya bertemu dengan
        `stock.move.line._spread_pallet_lot_excess()` -- dua jalur, satu hasil.
        """
        pallet = self._make_pallet()
        self._isi_pallet(pallet)

        pick = self._make_pick(self.total_isi)
        baris = pick.move_line_ids.filtered(lambda l: l.lot_id == self.lot_besar)
        baris.with_context(skip_pallet_lot_spread=True).write({
            'quantity': self.isi[self.lot_besar] + 250.0,
        })
        pick.move_line_ids.write({'picked': True})

        pick._take_full_package(pallet)
        self.assertEqual(self._qty_per_lot(pick, pallet), self.isi)

    # ==================================================================
    # 3. Sifat-sifat yang harus dijaga
    # ==================================================================
    def test_05_idempoten(self):
        """Panggilan kedua tidak boleh mengubah apa pun."""
        pallet = self._make_pallet()
        self._isi_pallet(pallet)

        pick = self._make_pick(self.total_isi)
        pick.move_line_ids.filtered(lambda l: l.lot_id == self.lot_hilang).unlink()
        pick.move_line_ids.write({'picked': True})

        pick._take_full_package(pallet)
        sebelum = self._qty_per_lot(pick, pallet)

        laporan = pick._take_full_package(pallet)
        self.assertFalse(laporan['dibuat'], laporan)
        self.assertFalse(laporan['diubah'], laporan)
        self.assertEqual(self._qty_per_lot(pick, pallet), sebelum)

    def test_06_pallet_yang_sebagian_dipegang_dokumen_lain_tetap_diambil_utuh(self):
        """Aturan bisnisnya: scan pallet mengambil seluruh isinya.

        Bagian yang dibooking dokumen lain dilepas core lewat
        `_free_reservation()` saat Validate -- sama dengan yang sudah dikunci
        `test_pick_package_multi_lot.py`.
        """
        pallet = self._make_pallet()
        self._isi_pallet(pallet)

        # Dokumen lain membooking satu lot lebih dulu.
        lain = self._make_pick(self.isi[self.lot_hilang])
        self.assertEqual(lain.move_line_ids.lot_id, self.lot_hilang)

        pick = self._make_pick(self.total_isi)
        pick.move_line_ids.write({'picked': True})
        self.assertNotIn(
            self.lot_hilang, self._qty_per_lot(pick, pallet),
            "Reservasi normal memang tidak kebagian lot yang sudah dipegang.",
        )

        pick._take_full_package(pallet)
        self.assertEqual(
            self._qty_per_lot(pick, pallet), self.isi,
            "Scan pallet tetap mengambil seluruh isinya.",
        )

    def test_07_validate_lolos_setelah_pallet_dilengkapi(self):
        """Rangkaian penuh: dilengkapi -> pallet pindah utuh, Validate tidak ditolak."""
        pallet = self._make_pallet()
        self._isi_pallet(pallet)

        pick = self._make_pick(self.total_isi)
        pick.move_line_ids.filtered(lambda l: l.lot_id == self.lot_hilang).unlink()
        pick.move_line_ids.write({'picked': True})
        pick._take_full_package(pallet)

        res = pick.with_context(test_stock_no_negative=True).button_validate()
        self.assertNotIsInstance(res, dict, "button_validate minta wizard: %s" % (res,))
        self.assertEqual(pick.state, 'done')

        self.env.invalidate_all()
        pindah = self.env['stock.quant'].sudo().search([
            ('product_id', '=', self.product.id),
            ('package_id', '=', pallet.id),
            ('location_id', '=', self.loc_dest.id),
        ])
        self.assertEqual(
            {q.lot_id: q.quantity for q in pindah}, self.isi,
            "Seluruh isi pallet harus pindah bersama pallet-nya.",
        )

    def test_08_produk_yang_tidak_ada_di_picking_dilaporkan_bukan_dipaksakan(self):
        """Pallet berisi produk lain: dilaporkan `dilewati`, tidak dibuatkan move."""
        produk_lain = self.env['product.product'].create({
            'name': 'UT FP Produk Lain',
            'default_code': 'UT-FP-LAIN',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'none',
        })
        pallet = self._make_pallet()
        self._isi_pallet(pallet)
        self.env['stock.quant']._update_available_quantity(
            produk_lain, self.loc_src, 50.0, package_id=pallet,
        )

        pick = self._make_pick(self.total_isi)
        pick.move_line_ids.write({'picked': True})

        laporan = pick._take_full_package(pallet)
        self.assertEqual(laporan['dilewati'], [(produk_lain.id, False)], laporan)
        self.assertFalse(
            pick.move_ids.filtered(lambda m: m.product_id == produk_lain),
            "Tidak boleh membuat move baru untuk produk di luar dokumen.",
        )

    def test_09_pallet_di_lokasi_lain_tidak_disentuh(self):
        """Pallet yang bukan di source location picking ini diabaikan."""
        loc_lain = self.env['stock.location'].create({
            'name': 'UT-FP-LAIN',
            'location_id': self.warehouse.lot_stock_id.id,
            'usage': 'internal',
            'company_id': self.company.id,
        })
        pallet = self._make_pallet()
        self._isi_pallet(pallet)

        pick = self._make_pick(self.total_isi)
        pick.move_line_ids.write({'picked': True})
        pick.write({'location_id': loc_lain.id})

        laporan = pick._take_full_package(pallet)
        self.assertEqual(laporan, {'dibuat': [], 'diubah': [], 'dilewati': []})
