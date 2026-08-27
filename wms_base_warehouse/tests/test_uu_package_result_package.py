"""Unit test: scan pallet pada picking `UU Only` harus mengambil SELURUH isinya.

Direproduksi dari kejadian nyata **S00764 / FINI/PICK/26/6356/1608953947**
(DB_WMS_DEV_008, Operation Type `Pick` id 11 -- `uu_only=True`):

    stock.package 25453 "SPJ-PALLET-10425" -- isi 1.280
        +-- lot 1485 "160110003515|95"       200
        +-- lot 1642 "23765636 - 12022028"   740
        +-- lot 1671 "32765636 - 12022028"    40
        +-- lot 1559 "160110003515|71"       300

Operator men-scan pallet itu, tapi move line yang terbentuk cuma **1.180**: baris
lot 1642 berhenti di **640**, yaitu angka RESERVASI-nya, bukan 740 isi quant-nya
(100 sisanya dipegang FINI/PICK/26/6334/1601033959). Karena
`stock.move._autofill_result_package()` tetap memasang pallet itu sebagai
destination package, saat Validate 1.180 box pindah MEMBAWA pallet 25453
sementara 100 box tertinggal di lokasi asal DI DALAM pallet 25453 juga. Core
menolaknya di `stock.move._action_done()`:

    "You cannot move the same package content more than once in the same
     transfer or split the same package into two location."

Dua hal yang diuji di sini:

1. **Kontraknya**: scan pallet = seluruh isi pallet terambil -> Validate lolos
   dan pallet pindah utuh (test_01, test_02).
2. **Pengamannya**: kalau yang terambil kurang, `_check_uu_package_fully_taken()`
   menolak dengan pesan yang MENYEBUT pallet, lot, dan kekurangannya -- bukan
   pesan core yang tidak menyebut apa-apa (test_03, test_04).

Yang penting untuk tidak salah tuduh: hanya baris `picked` yang dihitung. Sisa
reservasi yang belum di-scan memang tidak ikut pindah -- core menghapusnya di
`_action_done()` -- jadi tidak boleh membuat pallet dianggap pecah (test_05).

Jalankan:
    python odoo-bin -c wms.conf -u wms_base_warehouse --test-enable \\
        --test-tags wms_uu_package --stop-after-init --no-http
"""

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'wms_uu_package')
class TestUuPackageResultPackage(TransactionCase):

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

        # `_is_gr_prod()` melempar ValidationError kalau parameter ini kosong,
        # dan method itu dilewati hampir setiap create/write move line.
        icp = cls.env['ir.config_parameter'].sudo()
        if not icp.get_param('prod_in_move_type'):
            icp.set_param('prod_in_move_type', '101')
        icp.set_param('upload_stock', 'false')

        Location = cls.env['stock.location']
        cls.loc_src = Location.create({
            'name': 'UT-UU-SRC',
            'location_id': cls.warehouse.lot_stock_id.id,
            'usage': 'internal',
            'company_id': cls.company.id,
        })
        cls.loc_dest = Location.create({
            'name': 'UT-UU-DEST',
            'location_id': cls.warehouse.lot_stock_id.id,
            'usage': 'internal',
            'company_id': cls.company.id,
        })

        cls.product = cls.env['product.product'].create({
            'name': 'UT UU Pallet Product',
            'default_code': 'UT-UU-PALLET',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'lot',
        })

        # Empat lot persis seperti isi SPJ-PALLET-10425.
        Lot = cls.env['stock.lot']
        cls.isi_pallet = {}
        for name, qty in [
            ('UT-160110003515|95', 200.0),
            ('UT-23765636 - 12022028', 740.0),
            ('UT-32765636 - 12022028', 40.0),
            ('UT-160110003515|71', 300.0),
        ]:
            lot = Lot.create({
                'name': name,
                'product_id': cls.product.id,
                'company_id': cls.company.id,
            })
            cls.isi_pallet[lot] = qty
        cls.lot_besar = next(lot for lot, qty in cls.isi_pallet.items() if qty == 740.0)
        cls.total_isi = sum(cls.isi_pallet.values())   # 1280

        cls.type_uu = cls.env['stock.picking.type'].create({
            'name': 'UT UU Pick',
            'sequence_code': 'UTUU',
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
    def _make_pallet(self, name='UT-SPJ-PALLET-10425'):
        package = self.env['stock.package'].create({
            'name': name,
            'company_id': self.company.id,
        })
        package.yellow_tag = 'ready'  # syarat _gather() saat context uu_only
        return package

    def _isi_pallet(self, package, isi=None):
        """Isi pallet sesuai peta {lot: qty}. Urutan dict = urutan FIFO."""
        Quant = self.env['stock.quant']
        for lot, qty in (isi or self.isi_pallet).items():
            Quant._update_available_quantity(
                self.product, self.loc_src, qty, lot_id=lot, package_id=package,
            )
        quants = Quant.sudo().search([
            ('product_id', '=', self.product.id),
            ('package_id', '=', package.id),
        ])
        quants.write({'stock_type': 'UU'})  # syarat _gather() saat context uu_only
        return quants

    def _make_pick(self, qty):
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
        picking.action_assign()
        return picking

    def _scan_seluruh_pallet(self, picking, package):
        """Hasil scan pallet yang BENAR: tiap lot sebesar isi lot itu di pallet."""
        for line in picking.move_line_ids.filtered(lambda l: l.package_id == package):
            line.write({
                'quantity': self.isi_pallet[line.lot_id],
                'picked': True,
            })

    def _scan_pallet_kurang(self, picking, package, kurang=100.0):
        """Hasil scan yang jadi bug S00764: satu lot berhenti di angka reservasi."""
        for line in picking.move_line_ids.filtered(lambda l: l.package_id == package):
            qty = self.isi_pallet[line.lot_id]
            if line.lot_id == self.lot_besar:
                qty -= kurang
            line.write({'quantity': qty, 'picked': True})

    def _validate(self, picking, **ctx):
        picking = picking.with_context(test_stock_no_negative=True, **ctx)
        res = picking.button_validate()
        self.assertNotIsInstance(
            res, dict, "button_validate %s minta wizard: %s" % (picking.name, res),
        )
        return res

    def _qty_picked(self, picking, package):
        return sum(
            picking.move_line_ids.filtered(
                lambda l: l.package_id == package and l.picked
            ).mapped('quantity')
        )

    # ==================================================================
    # 1. Kontrak: scan pallet = ambil seluruh isinya
    # ==================================================================
    def test_01_reservasi_pallet_penuh_menutup_seluruh_isi(self):
        """Demand cukup -> reservasi sudah menutup keempat lot di pallet."""
        pallet = self._make_pallet()
        self._isi_pallet(pallet)

        pick = self._make_pick(self.total_isi)
        lines = pick.move_line_ids

        self.assertEqual(len(lines), 4, "Tiap lot di pallet punya move line sendiri.")
        self.assertEqual(
            {line.lot_id: line.quantity for line in lines}, self.isi_pallet,
            "Reservasi tiap lot harus sebesar isi lot itu di pallet.",
        )
        self.assertEqual(
            set(lines.mapped('result_package_id')), {pallet},
            "Picking UU membawa pallet-nya sebagai destination package.",
        )

    def test_02_scan_seluruh_isi_pallet_bisa_divalidasi(self):
        """1.280 dari 1.280 -> Validate lolos, pallet pindah utuh.

        Inilah keadaan yang benar; sebelum diperbaiki, scan berhenti di 1.180.
        """
        pallet = self._make_pallet()
        self._isi_pallet(pallet)

        pick = self._make_pick(self.total_isi)
        self._scan_seluruh_pallet(pick, pallet)
        self.assertEqual(self._qty_picked(pick, pallet), self.total_isi)

        self._validate(pick)
        self.assertEqual(pick.state, 'done')

        self.env.invalidate_all()
        pindah = self.env['stock.quant'].sudo().search([
            ('product_id', '=', self.product.id),
            ('package_id', '=', pallet.id),
            ('location_id', '=', self.loc_dest.id),
        ])
        self.assertEqual(
            {q.lot_id: q.quantity for q in pindah}, self.isi_pallet,
            "Seluruh isi pallet harus pindah bersama pallet-nya.",
        )
        tertinggal = self.env['stock.quant'].sudo().search([
            ('product_id', '=', self.product.id),
            ('package_id', '=', pallet.id),
            ('location_id', '=', self.loc_src.id),
        ])
        self.assertFalse(
            tertinggal.filtered(lambda q: q.quantity), "Tidak boleh ada sisa di lokasi asal.",
        )

    # ==================================================================
    # 2. Bug S00764: scan kurang 100
    # ==================================================================
    def test_03_scan_kurang_ditolak_sebelum_sampai_ke_core(self):
        """1.180 dari 1.280 -> ditolak dengan pesan yang menyebut pallet & lot.

        Sebelum ada `_check_uu_package_fully_taken()`, yang keluar adalah pesan
        core "You cannot move the same package content more than once..." yang
        tidak menyebut pallet mana pun, sehingga operator tidak tahu harus
        men-scan ulang yang mana.
        """
        pallet = self._make_pallet()
        self._isi_pallet(pallet)

        pick = self._make_pick(self.total_isi)
        self._scan_pallet_kurang(pick, pallet, kurang=100.0)
        self.assertEqual(self._qty_picked(pick, pallet), self.total_isi - 100.0)

        with self.assertRaises(ValidationError) as err:
            self._validate(pick)

        pesan = str(err.exception)
        self.assertIn(pallet.name, pesan, "Pesan harus menyebut pallet yang pecah.")
        self.assertIn(self.lot_besar.name, pesan, "Pesan harus menyebut lot yang kurang.")
        self.assertIn('100.0', pesan, "Pesan harus menyebut besar kekurangannya.")
        self.assertNotIn(
            'more than once', pesan,
            "Harus ditolak lebih dulu di sini, bukan sampai ke pesan core.",
        )
        self.assertNotEqual(pick.state, 'done')

    def test_04_scan_kurang_terdeteksi_per_pallet(self):
        """`_get_partially_taken_packages()` melaporkan pallet + selisih per lot."""
        pallet = self._make_pallet()
        self._isi_pallet(pallet)

        pick = self._make_pick(self.total_isi)
        self._scan_pallet_kurang(pick, pallet, kurang=100.0)

        laporan = pick._get_partially_taken_packages()
        self.assertEqual(list(laporan), [pallet])
        self.assertEqual(laporan[pallet], {self.lot_besar: 100.0})

        # Dilengkapi -> tidak dilaporkan lagi.
        self._scan_seluruh_pallet(pick, pallet)
        self.assertFalse(pick._get_partially_taken_packages())

    # ==================================================================
    # 3. Yang TIDAK boleh ikut kena
    # ==================================================================
    def test_05_sisa_reservasi_yang_belum_discan_tidak_dianggap_pecah(self):
        """Pallet kedua cuma ter-reserve, belum di-scan -> tidak menghalangi.

        Ini yang membuat dokumen nyata punya 16 pallet tapi cuma satu yang
        di-scan: `_action_done()` menghapus move line yang tidak `picked`, jadi
        pallet lain memang tidak ikut pindah dan tidak boleh dihitung pecah.
        """
        pallet_scan = self._make_pallet('UT-SPJ-PALLET-DISCAN')
        self._isi_pallet(pallet_scan)
        pallet_diam = self._make_pallet('UT-SPJ-PALLET-DIAM')
        self._isi_pallet(pallet_diam)

        pick = self._make_pick(self.total_isi * 2)
        self._scan_seluruh_pallet(pick, pallet_scan)

        sisa = pick.move_line_ids.filtered(lambda l: l.package_id == pallet_diam)
        self.assertTrue(sisa, "Pallet kedua harus ikut ter-reserve.")
        self.assertFalse(any(sisa.mapped('picked')), "Tapi belum di-scan.")
        self.assertFalse(
            pick._get_partially_taken_packages(),
            "Reservasi yang belum di-scan tidak boleh dianggap pallet pecah.",
        )

        self._validate(pick, skip_backorder=True)
        self.assertEqual(pick.state, 'done')

        self.env.invalidate_all()
        self.assertEqual(
            sum(self.env['stock.quant'].sudo().search([
                ('package_id', '=', pallet_diam.id),
                ('location_id', '=', self.loc_src.id),
            ]).mapped('quantity')),
            self.total_isi,
            "Pallet yang tidak di-scan harus utuh di lokasi asal.",
        )

    def test_06_barang_yang_dipindah_ke_pallet_muatan_tidak_kena(self):
        """Ambil eceran ke pallet lain itu sah -- tidak ada pallet di dua lokasi."""
        pallet = self._make_pallet()
        self._isi_pallet(pallet)
        pallet_muatan = self._make_pallet('UT-SPJ-PALLET-MUATAN')

        pick = self._make_pick(self.total_isi)
        self._scan_pallet_kurang(pick, pallet, kurang=100.0)
        pick.move_line_ids.filtered(lambda l: l.package_id == pallet).write({
            'result_package_id': pallet_muatan.id,
        })

        self.assertFalse(
            pick._get_partially_taken_packages(),
            "Destination package pallet lain tidak boleh kena pemeriksaan ini.",
        )
        self._validate(pick, skip_backorder=True)
        self.assertEqual(pick.state, 'done')

    def test_07_pemeriksaan_bisa_dilewati_lewat_context(self):
        """`skip_uu_package_check` menyerahkan kembali penolakan ke core.

        Disediakan untuk keadaan darurat/skrip; buktinya pesan yang keluar jadi
        pesan core lagi -- sekaligus menunjukkan pemeriksaan di atas memang
        menggantikan error yang sama, bukan menambah larangan baru.
        """
        pallet = self._make_pallet()
        self._isi_pallet(pallet)

        pick = self._make_pick(self.total_isi)
        self._scan_pallet_kurang(pick, pallet, kurang=100.0)

        with self.assertRaises(Exception) as err:
            self._validate(pick, skip_uu_package_check=True, skip_backorder=True)
        self.assertIn('more than once', str(err.exception))
