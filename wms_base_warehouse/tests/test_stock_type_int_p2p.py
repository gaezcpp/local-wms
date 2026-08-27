"""Uji propagasi `stock_type` (dan field tambahan lain) pada Operation Type
`Bin to Bin` (prefix INT) dan `Split QTY Pallet` (prefix P2P).

Skenario yang dikeluhkan: stok yang di lokasi asal berstatus **UU dan belum
punya package**, lalu dimasukkan ke package lewat kedua operation type itu,
kadang berubah jadi **QI** di package tujuan.

Rantai nilainya begini:

    stock.quant(asal).stock_type
        -> stock.move.line.stock_type      (jalur A: reservasi, jalur B: create dari Barcode)
        -> stock.quant(tujuan).stock_type   (stock.move._action_done -> _propagate_stock_type_to_quants)

Jadi kalau move line-nya salah, quant tujuan pasti ikut salah. Test di bawah
memeriksa tiap sambungan rantai itu satu per satu.

Jalankan:
    python odoo-bin -c wms.conf -d DB_WMS_DEV_008 --test-enable --stop-after-init \\
        --test-tags /wms_base_warehouse:TestStockTypeIntP2P
"""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'wms_stock_type')
class TestStockTypeIntP2P(TransactionCase):

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
        # Matikan jalur beginning stock supaya _sync_to_lot_aft() tidak ikut
        # bermain di tengah assertion.
        icp.set_param('upload_stock', 'false')

        Location = cls.env['stock.location']
        cls.bin_a = Location.create({
            'name': 'ST-BIN-A',
            'location_id': cls.warehouse.lot_stock_id.id,
            'usage': 'internal',
            'company_id': cls.company.id,
        })
        cls.bin_b = Location.create({
            'name': 'ST-BIN-B',
            'location_id': cls.warehouse.lot_stock_id.id,
            'usage': 'internal',
            'company_id': cls.company.id,
        })

        Product = cls.env['product.product']
        cls.product_lot = Product.create({
            'name': 'ST Product Lot',
            'default_code': 'ST-LOT',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'lot',
        })
        cls.product_plain = Product.create({
            'name': 'ST Product Plain',
            'default_code': 'ST-PLAIN',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'none',
        })

        Lot = cls.env['stock.lot']
        cls.lot_uu = Lot.create({
            'name': 'ST-LOT-UU',
            'product_id': cls.product_lot.id,
            'company_id': cls.company.id,
        })
        cls.lot_qi = Lot.create({
            'name': 'ST-LOT-QI',
            'product_id': cls.product_lot.id,
            'company_id': cls.company.id,
        })

        cls.production_line = cls.env['production.line'].create({
            'name': 'ST Line 1',
            'code': 'STL1',
            'company_id': cls.company.id,
        })

        cls.type_int = cls._make_picking_type('ST Bin to Bin', 'INT', split_package=False)
        cls.type_p2p = cls._make_picking_type('ST Split QTY Pallet', 'P2P', split_package=True)
        cls.type_gr = cls._make_picking_type(
            'ST GR Produksi', 'STGR',
            move_type_sap=cls.env['ir.config_parameter'].sudo().get_param('prod_in_move_type'),
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @classmethod
    def _make_picking_type(cls, name, sequence_code, split_package=False, move_type_sap=False):
        """Tiruan konfigurasi asli: INT/P2P sama-sama internal, uu_only=False,
        move_type_sap kosong (jadi bukan GR produksi)."""
        return cls.env['stock.picking.type'].create({
            'name': name,
            'sequence_code': sequence_code,
            'code': 'internal',
            'warehouse_id': cls.warehouse.id,
            'company_id': cls.company.id,
            'default_location_src_id': cls.bin_a.id,
            'default_location_dest_id': cls.bin_b.id,
            'uu_only': False,
            'split_package': split_package,
            'mandatory_destination': False,
            'book_full_pallet': False,
            'move_type_sap': move_type_sap,
        })

    def _make_package(self, name):
        return self.env['stock.package'].create({'name': name})

    def _make_quant(self, product, location, qty, stock_type,
                    lot=None, package=None, production_line=None, pallet_ke=0):
        return self.env['stock.quant'].create({
            'product_id': product.id,
            'location_id': location.id,
            'lot_id': lot.id if lot else False,
            'package_id': package.id if package else False,
            'quantity': qty,
            'stock_type': stock_type,
            'production_line_id': production_line.id if production_line else False,
            'pallet_ke': pallet_ke,
        })

    def _make_picking(self, picking_type, product, qty, src=None, dest=None):
        src = src or self.bin_a
        dest = dest or self.bin_b
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': src.id,
            'location_dest_id': dest.id,
            'company_id': self.company.id,
            'move_ids': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
                'location_id': src.id,
                'location_dest_id': dest.id,
                'company_id': self.company.id,
            })],
        })
        picking.action_confirm()
        picking.action_assign()
        return picking

    def _barcode_create_line(self, picking, product, qty, location,
                             location_dest=None, lot=None, package=None,
                             result_package=None):
        """Tiruan persis `_createCommandVals()` milik stock_barcode.

        Perhatikan: **`stock_type` tidak ada di dalamnya**, karena
        `_getFieldToWrite()` (core maupun patch wms_inherit_stock_barcode)
        tidak pernah menyertakan field itu. Jadi nilainya sepenuhnya
        ditentukan server, lewat `stock.move.line.create()` di
        wms_base_warehouse.
        """
        picking.write({'move_line_ids': [(0, 0, {
            'is_entire_pack': False,
            'location_id': location.id,
            'location_dest_id': (location_dest or picking.location_dest_id).id,
            'lot_id': lot.id if lot else False,
            'owner_id': False,
            'package_id': package.id if package else False,
            'picking_id': picking.id,
            'picked': True,
            'product_id': product.id,
            'product_uom_id': product.uom_id.id,
            'quantity': qty,
            'result_package_id': result_package.id if result_package else False,
            'state': 'assigned',
        })]})
        return picking.move_line_ids.sorted('id')[-1]

    def _dest_quant(self, product, location, lot=None, package=None):
        domain = [
            ('product_id', '=', product.id),
            ('location_id', '=', location.id),
        ]
        if lot:
            domain.append(('lot_id', '=', lot.id))
        if package:
            domain.append(('package_id', '=', package.id))
        else:
            domain.append(('package_id', '=', False))
        return self.env['stock.quant'].search(domain)

    # ==================================================================
    # 1. Jalur reservasi (`_prepare_move_line_vals`)
    # ==================================================================
    def test_int_reserved_line_inherits_uu(self):
        """INT: move line hasil reservasi harus mewarisi stock_type quant asal."""
        self._make_quant(self.product_lot, self.bin_a, 100.0, 'UU', lot=self.lot_uu)

        picking = self._make_picking(self.type_int, self.product_lot, 100.0)
        line = picking.move_line_ids

        self.assertEqual(len(line), 1)
        self.assertEqual(
            line.stock_type, 'UU',
            "stock_type move line hasil reservasi tidak mengikuti quant asal "
            "(dapat %s)" % line.stock_type,
        )

    def test_p2p_reserved_line_inherits_uu(self):
        """P2P: sama, walau `_action_assign()` menghapus result_package_id."""
        self._make_quant(self.product_lot, self.bin_a, 100.0, 'UU', lot=self.lot_uu)

        picking = self._make_picking(self.type_p2p, self.product_lot, 100.0,
                                     dest=self.bin_a)
        line = picking.move_line_ids

        self.assertEqual(len(line), 1)
        self.assertFalse(line.result_package_id,
                         "split_package seharusnya mengosongkan result_package_id")
        self.assertEqual(line.stock_type, 'UU')

    # ==================================================================
    # 2. Jalur create dari Barcode (`stock.move.line.create`)
    # ==================================================================
    def test_int_barcode_line_inherits_uu_from_loose_quant(self):
        """Stok UU tanpa package, discan lewat Barcode -> line harus UU."""
        self._make_quant(self.product_lot, self.bin_a, 100.0, 'UU', lot=self.lot_uu)
        picking = self._make_picking(self.type_int, self.product_lot, 100.0)
        picking.move_line_ids.unlink()

        line = self._barcode_create_line(
            picking, self.product_lot, 40.0, self.bin_a, lot=self.lot_uu,
        )
        self.assertEqual(
            line.stock_type, 'UU',
            "Line hasil scan Barcode tidak mewarisi UU dari quant asal "
            "(dapat %s)" % line.stock_type,
        )

    def test_int_barcode_line_without_matching_quant_must_not_default_to_qi(self):
        """Kalau quant asal tidak ketemu, stock_type TIDAK boleh jadi 'QI'.

        `stock.move.line.stock_type` punya `default='QI'`. Setiap kali lookup
        quant di `create()` gagal (lot belum punya quant di lokasi itu, atau
        `location_id`/`product_id` tidak ikut dikirim), nilai QI itulah yang
        dipakai -- diam-diam, tanpa error. Itu sumber "UU tiba-tiba jadi QI".
        """
        # Stok UU-nya ada, tapi lot yang discan berbeda -> lookup tidak match.
        self._make_quant(self.product_lot, self.bin_a, 100.0, 'UU', lot=self.lot_uu)
        picking = self._make_picking(self.type_int, self.product_lot, 100.0)
        picking.move_line_ids.unlink()

        line = self._barcode_create_line(
            picking, self.product_lot, 40.0, self.bin_a, lot=self.lot_qi,
        )
        self.assertNotEqual(
            line.stock_type, 'QI',
            "Lookup quant gagal, tapi field tetap diisi 'QI' oleh default field. "
            "Seharusnya kosong (atau ditolak), bukan diam-diam jadi QI.",
        )

    def test_int_barcode_line_must_not_borrow_stock_type_from_other_package(self):
        """Filter package di `create()` dilewati kalau line-nya tanpa package.

        Kondisinya persis yang dilaporkan: stok yang discan **belum punya
        package**. Karena `vals['package_id']` kosong, syarat package di
        `filtered()` tidak dipasang sama sekali, jadi quant milik package lain
        di bin yang sama ikut jadi kandidat -- dan `matching_quants[0]`
        (urutan default = id terkecil) yang menang.
        """
        pkg_qi = self._make_package('ST-PKG-QI')
        # Quant QI dibuat lebih dulu -> id lebih kecil -> menang di [0].
        self._make_quant(self.product_plain, self.bin_a, 50.0, 'QI', package=pkg_qi)
        self._make_quant(self.product_plain, self.bin_a, 100.0, 'UU')

        picking = self._make_picking(self.type_int, self.product_plain, 100.0)
        picking.move_line_ids.unlink()

        line = self._barcode_create_line(
            picking, self.product_plain, 40.0, self.bin_a,
        )
        self.assertEqual(
            line.stock_type, 'UU',
            "Line tanpa package mengambil stock_type dari quant milik package "
            "lain di bin yang sama (dapat %s)." % line.stock_type,
        )

    # ==================================================================
    # 3. End-to-end: loose UU -> masuk package
    # ==================================================================
    def test_int_put_loose_uu_into_package_keeps_uu(self):
        """INT Bin to Bin: UU tanpa package -> dimasukkan package -> tetap UU."""
        self._make_quant(self.product_lot, self.bin_a, 100.0, 'UU', lot=self.lot_uu)
        picking = self._make_picking(self.type_int, self.product_lot, 100.0)

        pkg = self._make_package('ST-PKG-INT')
        picking.move_line_ids.write({'result_package_id': pkg.id, 'picked': True})
        picking.button_validate()

        self.assertEqual(picking.state, 'done')
        quant = self._dest_quant(self.product_lot, self.bin_b,
                                 lot=self.lot_uu, package=pkg)
        self.assertTrue(quant, "Quant tujuan tidak terbentuk")
        self.assertEqual(
            quant.stock_type, 'UU',
            "stock_type quant tujuan berubah jadi %s" % quant.stock_type,
        )

    def test_p2p_put_loose_uu_into_package_keeps_uu(self):
        """P2P Split QTY Pallet: UU tanpa package -> dimasukkan package -> tetap UU."""
        self._make_quant(self.product_lot, self.bin_a, 100.0, 'UU', lot=self.lot_uu)
        picking = self._make_picking(self.type_p2p, self.product_lot, 100.0,
                                     dest=self.bin_a)

        pkg = self._make_package('ST-PKG-P2P')
        picking.move_line_ids.write({'result_package_id': pkg.id, 'picked': True})
        picking.button_validate()

        self.assertEqual(picking.state, 'done')
        quant = self._dest_quant(self.product_lot, self.bin_a,
                                 lot=self.lot_uu, package=pkg)
        self.assertTrue(quant, "Quant tujuan tidak terbentuk")
        self.assertEqual(
            quant.stock_type, 'UU',
            "stock_type quant tujuan berubah jadi %s" % quant.stock_type,
        )

    def test_p2p_partial_split_keeps_uu_on_both_sides(self):
        """Split sebagian: yang masuk package UU, sisa yang loose juga tetap UU."""
        self._make_quant(self.product_lot, self.bin_a, 100.0, 'UU', lot=self.lot_uu)
        picking = self._make_picking(self.type_p2p, self.product_lot, 40.0,
                                     dest=self.bin_a)

        pkg = self._make_package('ST-PKG-P2P-PART')
        picking.move_line_ids.write({
            'quantity': 40.0,
            'result_package_id': pkg.id,
            'picked': True,
        })
        picking.button_validate()

        packed = self._dest_quant(self.product_lot, self.bin_a,
                                  lot=self.lot_uu, package=pkg)
        loose = self._dest_quant(self.product_lot, self.bin_a, lot=self.lot_uu)

        self.assertEqual(packed.stock_type, 'UU',
                         "Bagian yang dipack berubah jadi %s" % packed.stock_type)
        self.assertEqual(sum(loose.mapped('quantity')), 60.0)
        self.assertEqual(set(loose.mapped('stock_type')), {'UU'},
                         "Sisa loose berubah jadi %s" % loose.mapped('stock_type'))

    def test_int_barcode_flow_loose_uu_into_package_keeps_uu(self):
        """Rangkaian penuh seperti di scanner: line dibuat Barcode, lalu divalidate.

        Ini yang paling dekat dengan kejadian nyata -- line tidak berasal dari
        reservasi, tapi dari `_createCommandVals()`.
        """
        self._make_quant(self.product_lot, self.bin_a, 100.0, 'UU', lot=self.lot_uu)
        picking = self._make_picking(self.type_int, self.product_lot, 100.0)
        picking.move_line_ids.unlink()

        pkg = self._make_package('ST-PKG-INT-BC')
        self._barcode_create_line(
            picking, self.product_lot, 100.0, self.bin_a,
            lot=self.lot_uu, result_package=pkg,
        )
        picking.button_validate()

        quant = self._dest_quant(self.product_lot, self.bin_b,
                                 lot=self.lot_uu, package=pkg)
        self.assertTrue(quant, "Quant tujuan tidak terbentuk")
        self.assertEqual(
            quant.stock_type, 'UU',
            "stock_type quant tujuan berubah jadi %s" % quant.stock_type,
        )

    # ==================================================================
    # 4. Regresi: GR produksi harus TETAP QI
    # ==================================================================
    def test_gr_prod_barcode_line_still_qi_without_source_quant(self):
        """Pengaman untuk penghapusan `default='QI'`.

        Dulu semua baris GR kebetulan dapat QI dari default field. Sekarang
        nilainya dipasang eksplisit oleh `_apply_gr_prod_stock_type()`, jadi
        alur GR tidak boleh ikut berubah walau quant asalnya tidak ada.
        """
        picking = self._make_picking(self.type_gr, self.product_lot, 100.0)
        picking.move_line_ids.unlink()

        line = self._barcode_create_line(
            picking, self.product_lot, 100.0, self.bin_a, lot=self.lot_uu,
        )
        self.assertEqual(
            line.stock_type, 'QI',
            "GR produksi kehilangan QI setelah default field dihapus "
            "(dapat %s)" % line.stock_type,
        )

    def test_gr_prod_reserved_line_still_qi(self):
        """Jalur reservasi GR: `_prepare_move_line_vals()` memaksa QI walau
        quant asalnya UU."""
        self._make_quant(self.product_lot, self.bin_a, 100.0, 'UU', lot=self.lot_uu)
        picking = self._make_picking(self.type_gr, self.product_lot, 100.0)

        self.assertEqual(picking.move_line_ids.stock_type, 'QI')

    def test_non_gr_line_without_source_quant_stays_empty(self):
        """Kebalikannya: baris non-GR yang tidak ketemu quant asal dibiarkan
        kosong, bukan diisi tebakan."""
        picking = self._make_picking(self.type_int, self.product_lot, 100.0)
        picking.move_line_ids.unlink()

        line = self._barcode_create_line(
            picking, self.product_lot, 100.0, self.bin_a, lot=self.lot_uu,
        )
        self.assertFalse(
            line.stock_type,
            "stock_type diisi %s padahal tidak ada quant asal yang bisa "
            "dijadikan rujukan" % line.stock_type,
        )

    # ==================================================================
    # 5. Field tambahan lain yang ikut hilang
    # ==================================================================
    def test_int_dest_quant_keeps_production_line_and_pallet_ke(self):
        """`production_line_id` dan `pallet_ke` quant asal harus ikut pindah.

        `stock.move.line._synchronize_quant()` menyalin keduanya ke quant
        tujuan lewat context, tapi hanya dari **move line**, bukan dari quant.
        Untuk INT/P2P (tanpa `move_orig_ids`) `_prepare_move_line_vals()` tidak
        pernah mengisi kedua field itu, jadi nilainya hilang di tujuan.
        """
        self._make_quant(
            self.product_lot, self.bin_a, 100.0, 'UU', lot=self.lot_uu,
            production_line=self.production_line, pallet_ke=7,
        )
        picking = self._make_picking(self.type_int, self.product_lot, 100.0)
        picking.move_line_ids.write({'picked': True})
        picking.button_validate()

        quant = self._dest_quant(self.product_lot, self.bin_b, lot=self.lot_uu)
        self.assertTrue(quant, "Quant tujuan tidak terbentuk")
        self.assertEqual(
            quant.production_line_id, self.production_line,
            "production_line_id hilang di quant tujuan",
        )
        self.assertEqual(
            quant.pallet_ke, 7,
            "pallet_ke hilang di quant tujuan (dapat %s)" % quant.pallet_ke,
        )
