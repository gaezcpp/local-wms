"""Uji `stock_type` pada siklus **unpack -> Split QTY Pallet -> masuk package lagi**.

Keluhan lapangan: qty yang dikeluarkan dari sebuah `stock.package` (unpack),
lalu dimasukkan kembali ke package lewat operation type `Split QTY Pallet`
(P2P), `stock_type`-nya berubah -- UU bisa jadi QI, atau malah kosong.

Rantai nilainya:

    stock.quant(dalam package).stock_type
        -> [unpack] stock.quant(loose di bin).stock_type
        -> stock.move.line.stock_type      (reservasi ATAU create dari Barcode)
        -> stock.quant(package baru).stock_type

Test di bawah memeriksa tiap sambungan itu, termasuk kasus bin campur
(package lain dengan stock_type berbeda menempati bin yang sama) yang jadi
sumber "tertukar" paling sering.

Jalankan:
    python odoo-bin -c wms.conf -d DB_WMS_DEV_008 --test-enable --stop-after-init \\
        --test-tags /wms_base_warehouse:TestStockTypeUnpackRepack
"""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'wms_stock_type')
class TestStockTypeUnpackRepack(TransactionCase):

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
        cls.bin_a = Location.create({
            'name': 'UR-BIN-A',
            'location_id': cls.warehouse.lot_stock_id.id,
            'usage': 'internal',
            'company_id': cls.company.id,
        })
        cls.bin_b = Location.create({
            'name': 'UR-BIN-B',
            'location_id': cls.warehouse.lot_stock_id.id,
            'usage': 'internal',
            'company_id': cls.company.id,
        })

        Product = cls.env['product.product']
        cls.product_lot = Product.create({
            'name': 'UR Product Lot',
            'default_code': 'UR-LOT',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'lot',
        })
        cls.product_plain = Product.create({
            'name': 'UR Product Plain',
            'default_code': 'UR-PLAIN',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'none',
        })

        Lot = cls.env['stock.lot']
        cls.lot_uu = Lot.create({
            'name': 'UR-LOT-UU',
            'product_id': cls.product_lot.id,
            'company_id': cls.company.id,
        })
        cls.lot_qi = Lot.create({
            'name': 'UR-LOT-QI',
            'product_id': cls.product_lot.id,
            'company_id': cls.company.id,
        })

        cls.production_line = cls.env['production.line'].create({
            'name': 'UR Line 1',
            'code': 'URL1',
            'company_id': cls.company.id,
        })

        cls.type_p2p = cls._make_picking_type('UR Split QTY Pallet', 'URP2P',
                                              split_package=True)

        # Setup GR produksi: sumbernya lokasi virtual `Production`, dan nama lot
        # dihasilkan dari format `production.code` (lihat `_get_or_create_lot()`).
        cls.production_loc = cls.env['stock.location'].create({
            'name': 'UR-PRODUCTION',
            'usage': 'production',
            'company_id': cls.company.id,
        })
        cls.production_code = cls.env['production.code'].sudo().search(
            [('company_id', '=', cls.company.id)], limit=1
        )
        lot_format = 'UR-GR-{moveline.production_line_id.code}'
        if cls.production_code:
            cls.production_code.write({'code': lot_format})
        else:
            cls.production_code = cls.env['production.code'].sudo().create({
                'company_id': cls.company.id,
                'code': lot_format,
            })
        cls.type_gr = cls._make_picking_type(
            'UR GR Produksi', 'URGR', code='incoming',
            src=cls.production_loc, dest=cls.bin_a,
            move_type_sap=cls.env['ir.config_parameter'].sudo().get_param('prod_in_move_type'),
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @classmethod
    def _make_picking_type(cls, name, sequence_code, split_package=False,
                           move_type_sap=False, code='internal',
                           src=None, dest=None):
        return cls.env['stock.picking.type'].create({
            'name': name,
            'sequence_code': sequence_code,
            'code': code,
            'warehouse_id': cls.warehouse.id,
            'company_id': cls.company.id,
            'default_location_src_id': (src or cls.bin_a).id,
            'default_location_dest_id': (dest or cls.bin_a).id,
            'uu_only': False,
            'split_package': split_package,
            'mandatory_destination': False,
            'book_full_pallet': False,
            'move_type_sap': move_type_sap,
            'use_create_lots': True,
            'use_existing_lots': True,
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
        dest = dest or self.bin_a
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
        """Tiruan `_createCommandVals()` milik stock_barcode: TANPA `stock_type`."""
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

    def _quants(self, product, location, lot=None, package=None):
        domain = [
            ('product_id', '=', product.id),
            ('location_id', '=', location.id),
        ]
        if lot:
            domain.append(('lot_id', '=', lot.id))
        domain.append(('package_id', '=', package.id if package else False))
        return self.env['stock.quant'].search(domain).filtered(lambda q: q.quantity)

    def _unpack(self, package):
        """Unpack lewat jalur core (`stock.package.unpack()` -> `move_quants`)."""
        package.unpack()

    # ==================================================================
    # 1. Unpack saja: stock_type harus ikut keluar dari package
    # ==================================================================
    def test_unpack_keeps_stock_type_on_loose_quant(self):
        """Qty yang dilepas dari pallet tetap UU, bukan kosong/QI."""
        pkg = self._make_package('UR-PKG-UU')
        self._make_quant(self.product_lot, self.bin_a, 100.0, 'UU',
                         lot=self.lot_uu, package=pkg)

        self._unpack(pkg)

        loose = self._quants(self.product_lot, self.bin_a, lot=self.lot_uu)
        self.assertTrue(loose, "Quant loose hasil unpack tidak terbentuk")
        self.assertEqual(sum(loose.mapped('quantity')), 100.0)
        self.assertEqual(
            set(loose.mapped('stock_type')), {'UU'},
            "stock_type hilang/berubah setelah unpack (dapat %s)"
            % loose.mapped('stock_type'),
        )

    def test_unpack_blocked_keeps_blocked(self):
        """BLOCKED tidak boleh ikut luntur jadi QI/kosong saat unpack."""
        pkg = self._make_package('UR-PKG-BLOCKED')
        self._make_quant(self.product_lot, self.bin_a, 80.0, 'BLOCKED',
                         lot=self.lot_qi, package=pkg)

        self._unpack(pkg)

        loose = self._quants(self.product_lot, self.bin_a, lot=self.lot_qi)
        self.assertEqual(set(loose.mapped('stock_type')), {'BLOCKED'},
                         "BLOCKED berubah jadi %s" % loose.mapped('stock_type'))

    def test_unpack_does_not_borrow_from_other_package_in_same_bin(self):
        """Bin campur: pallet QI ada lebih dulu di bin yang sama.

        Quant QI dibuat duluan (id lebih kecil) supaya kalau pencocokan quant
        asal longgar, dialah yang menang -- persis pola bug lama di
        `_fill_from_source_quant()`.
        """
        pkg_qi = self._make_package('UR-PKG-MIX-QI')
        self._make_quant(self.product_plain, self.bin_a, 50.0, 'QI', package=pkg_qi)

        pkg_uu = self._make_package('UR-PKG-MIX-UU')
        self._make_quant(self.product_plain, self.bin_a, 100.0, 'UU', package=pkg_uu)

        self._unpack(pkg_uu)

        loose = self._quants(self.product_plain, self.bin_a)
        self.assertEqual(sum(loose.mapped('quantity')), 100.0)
        self.assertEqual(
            set(loose.mapped('stock_type')), {'UU'},
            "Qty UU hasil unpack mengambil stock_type pallet lain (dapat %s)"
            % loose.mapped('stock_type'),
        )
        self.assertEqual(
            self._quants(self.product_plain, self.bin_a, package=pkg_qi).stock_type,
            'QI', "Pallet QI di bin yang sama ikut tertimpa",
        )

    # ==================================================================
    # 2. Unpack -> Split QTY Pallet -> masuk package lagi
    # ==================================================================
    def test_unpack_then_p2p_repack_keeps_uu_barcode_flow(self):
        """Skenario keluhan, persis jalur scanner (line dibuat client Barcode)."""
        pkg_src = self._make_package('UR-PKG-SRC')
        self._make_quant(self.product_lot, self.bin_a, 100.0, 'UU',
                         lot=self.lot_uu, package=pkg_src)
        self._unpack(pkg_src)

        picking = self._make_picking(self.type_p2p, self.product_lot, 100.0)
        picking.move_line_ids.unlink()

        pkg_new = self._make_package('UR-PKG-NEW')
        line = self._barcode_create_line(
            picking, self.product_lot, 100.0, self.bin_a,
            lot=self.lot_uu, result_package=pkg_new,
        )
        self.assertEqual(
            line.stock_type, 'UU',
            "Move line hasil scan tidak mewarisi UU dari quant loose "
            "(dapat %s)" % line.stock_type,
        )

        picking.button_validate()
        self.assertEqual(picking.state, 'done')

        quant = self._quants(self.product_lot, self.bin_a,
                             lot=self.lot_uu, package=pkg_new)
        self.assertTrue(quant, "Quant di package baru tidak terbentuk")
        self.assertEqual(
            quant.stock_type, 'UU',
            "stock_type di package baru berubah jadi %s" % quant.stock_type,
        )

    def test_unpack_then_p2p_repack_keeps_uu_reserved_flow(self):
        """Jalur reservasi: `_prepare_move_line_vals()` dari quant loose."""
        pkg_src = self._make_package('UR-PKG-SRC-RES')
        self._make_quant(self.product_lot, self.bin_a, 100.0, 'UU',
                         lot=self.lot_uu, package=pkg_src)
        self._unpack(pkg_src)

        picking = self._make_picking(self.type_p2p, self.product_lot, 100.0)
        self.assertEqual(picking.move_line_ids.stock_type, 'UU')

        pkg_new = self._make_package('UR-PKG-NEW-RES')
        picking.move_line_ids.write({'result_package_id': pkg_new.id, 'picked': True})
        picking.button_validate()

        quant = self._quants(self.product_lot, self.bin_a,
                             lot=self.lot_uu, package=pkg_new)
        self.assertEqual(quant.stock_type, 'UU',
                         "stock_type di package baru berubah jadi %s" % quant.stock_type)

    def test_unpack_then_partial_repack_keeps_uu_on_both_sides(self):
        """Split sebagian setelah unpack: yang dipack dan sisanya sama-sama UU."""
        pkg_src = self._make_package('UR-PKG-PART-SRC')
        self._make_quant(self.product_lot, self.bin_a, 100.0, 'UU',
                         lot=self.lot_uu, package=pkg_src)
        self._unpack(pkg_src)

        picking = self._make_picking(self.type_p2p, self.product_lot, 40.0)
        picking.move_line_ids.unlink()

        pkg_new = self._make_package('UR-PKG-PART-NEW')
        self._barcode_create_line(
            picking, self.product_lot, 40.0, self.bin_a,
            lot=self.lot_uu, result_package=pkg_new,
        )
        picking.button_validate()

        packed = self._quants(self.product_lot, self.bin_a,
                              lot=self.lot_uu, package=pkg_new)
        loose = self._quants(self.product_lot, self.bin_a, lot=self.lot_uu)

        self.assertEqual(packed.stock_type, 'UU',
                         "Bagian yang dipack jadi %s" % packed.stock_type)
        self.assertEqual(sum(loose.mapped('quantity')), 60.0)
        self.assertEqual(set(loose.mapped('stock_type')), {'UU'},
                         "Sisa loose jadi %s" % loose.mapped('stock_type'))

    def test_unpack_repack_in_mixed_bin_keeps_own_stock_type(self):
        """Bin campur: pallet QI (produk & lot sama) menempati bin yang sama.

        Ini kondisi paling sering di gudang: satu bin dipakai beberapa pallet
        dengan status berbeda. Qty UU yang di-unpack lalu dipack ulang tidak
        boleh mewarisi QI dari tetangganya.
        """
        pkg_qi = self._make_package('UR-PKG-BIN-QI')
        self._make_quant(self.product_lot, self.bin_a, 50.0, 'QI',
                         lot=self.lot_qi, package=pkg_qi)

        pkg_uu = self._make_package('UR-PKG-BIN-UU')
        self._make_quant(self.product_lot, self.bin_a, 100.0, 'UU',
                         lot=self.lot_uu, package=pkg_uu)
        self._unpack(pkg_uu)

        picking = self._make_picking(self.type_p2p, self.product_lot, 100.0)
        picking.move_line_ids.unlink()

        pkg_new = self._make_package('UR-PKG-BIN-NEW')
        line = self._barcode_create_line(
            picking, self.product_lot, 100.0, self.bin_a,
            lot=self.lot_uu, result_package=pkg_new,
        )
        self.assertEqual(line.stock_type, 'UU',
                         "Line meminjam stock_type pallet QI (dapat %s)" % line.stock_type)

        picking.button_validate()
        self.assertEqual(
            self._quants(self.product_lot, self.bin_a,
                         lot=self.lot_uu, package=pkg_new).stock_type,
            'UU',
        )
        self.assertEqual(
            self._quants(self.product_lot, self.bin_a,
                         lot=self.lot_qi, package=pkg_qi).stock_type,
            'QI', "Pallet QI tetangga ikut berubah",
        )

    def test_repeated_unpack_repack_cycle_keeps_uu(self):
        """Dua siklus berturut-turut -- kondisi nyata pallet eceran."""
        pkg1 = self._make_package('UR-PKG-CYCLE-1')
        self._make_quant(self.product_lot, self.bin_a, 100.0, 'UU',
                         lot=self.lot_uu, package=pkg1)

        current = pkg1
        for cycle in range(2):
            self._unpack(current)
            loose = self._quants(self.product_lot, self.bin_a, lot=self.lot_uu)
            self.assertEqual(
                set(loose.mapped('stock_type')), {'UU'},
                "Siklus %s: stock_type loose jadi %s" % (cycle, loose.mapped('stock_type')),
            )

            picking = self._make_picking(self.type_p2p, self.product_lot, 100.0)
            picking.move_line_ids.unlink()
            current = self._make_package('UR-PKG-CYCLE-NEW-%s' % cycle)
            self._barcode_create_line(
                picking, self.product_lot, 100.0, self.bin_a,
                lot=self.lot_uu, result_package=current,
            )
            picking.button_validate()

            self.assertEqual(
                self._quants(self.product_lot, self.bin_a,
                             lot=self.lot_uu, package=current).stock_type,
                'UU', "Siklus %s: stock_type di package baru berubah" % cycle,
            )

    def test_unpack_then_repack_untracked_product_keeps_uu(self):
        """Produk tanpa lot: pencocokan quant hanya bisa lewat lokasi+package."""
        pkg_src = self._make_package('UR-PKG-PLAIN-SRC')
        self._make_quant(self.product_plain, self.bin_a, 120.0, 'UU', package=pkg_src)
        self._unpack(pkg_src)

        picking = self._make_picking(self.type_p2p, self.product_plain, 120.0)
        picking.move_line_ids.unlink()

        pkg_new = self._make_package('UR-PKG-PLAIN-NEW')
        self._barcode_create_line(
            picking, self.product_plain, 120.0, self.bin_a,
            result_package=pkg_new,
        )
        picking.button_validate()

        self.assertEqual(
            self._quants(self.product_plain, self.bin_a, package=pkg_new).stock_type,
            'UU',
        )

    def test_unpack_then_repack_keeps_production_line_and_pallet_ke(self):
        """Atribut turunan quant lain tidak boleh ikut hilang di siklus ini."""
        pkg_src = self._make_package('UR-PKG-ATTR-SRC')
        self._make_quant(self.product_lot, self.bin_a, 100.0, 'UU',
                         lot=self.lot_uu, package=pkg_src,
                         production_line=self.production_line, pallet_ke=3)
        self._unpack(pkg_src)

        loose = self._quants(self.product_lot, self.bin_a, lot=self.lot_uu)
        self.assertEqual(set(loose.mapped('production_line_id')), {self.production_line},
                         "production_line_id hilang setelah unpack")

        picking = self._make_picking(self.type_p2p, self.product_lot, 100.0)
        picking.move_line_ids.unlink()

        pkg_new = self._make_package('UR-PKG-ATTR-NEW')
        self._barcode_create_line(
            picking, self.product_lot, 100.0, self.bin_a,
            lot=self.lot_uu, result_package=pkg_new,
        )
        picking.button_validate()

        quant = self._quants(self.product_lot, self.bin_a,
                             lot=self.lot_uu, package=pkg_new)
        self.assertEqual(quant.stock_type, 'UU')
        self.assertEqual(quant.production_line_id, self.production_line,
                         "production_line_id hilang setelah dipack ulang")

    # ==================================================================
    # 3. Line yang diisi bertahap oleh client Barcode
    # ==================================================================
    # Client Barcode tidak mengirim satu baris sekali jadi: baris dibuat lebih
    # dulu (sering tanpa lot / tanpa package), lalu detailnya menyusul lewat
    # `write()` pada save berikutnya. Kalau `stock_type` hanya ditentukan sekali
    # di `create()`, nilainya terkunci pada tebakan awal -- inilah sisa jalur
    # yang masih bisa membuat UU berubah jadi QI atau kosong.

    def test_stock_type_follows_lot_written_after_create(self):
        """Lot menyusul di-write: stock_type harus ikut lot yang benar."""
        # QI dibuat lebih besar supaya tebakan awal (tanpa lot) jatuh ke QI.
        self._make_quant(self.product_lot, self.bin_a, 100.0, 'QI', lot=self.lot_qi)
        self._make_quant(self.product_lot, self.bin_a, 50.0, 'UU', lot=self.lot_uu)

        picking = self._make_picking(self.type_p2p, self.product_lot, 50.0)
        picking.move_line_ids.unlink()

        line = self._barcode_create_line(picking, self.product_lot, 50.0, self.bin_a)
        line.write({'lot_id': self.lot_uu.id})

        self.assertEqual(
            line.stock_type, 'UU',
            "stock_type masih terkunci pada tebakan saat create (dapat %s), "
            "padahal lot-nya sudah jelas UU" % line.stock_type,
        )

    def test_stock_type_follows_package_written_after_create(self):
        """Pallet menyusul di-scan: stock_type harus ikut isi pallet itu."""
        self._make_quant(self.product_plain, self.bin_a, 100.0, 'QI')
        pkg_uu = self._make_package('UR-PKG-LATE')
        self._make_quant(self.product_plain, self.bin_a, 60.0, 'UU', package=pkg_uu)

        picking = self._make_picking(self.type_p2p, self.product_plain, 60.0)
        picking.move_line_ids.unlink()

        line = self._barcode_create_line(picking, self.product_plain, 60.0, self.bin_a)
        line.write({'package_id': pkg_uu.id})

        self.assertEqual(
            line.stock_type, 'UU',
            "stock_type tidak ikut pallet yang di-scan belakangan (dapat %s)"
            % line.stock_type,
        )

    def test_validate_fills_stock_type_when_create_found_nothing(self):
        """Stok baru ada setelah baris dibuat (mis. pallet baru di-unpack).

        Saat `create()` tidak ada quant yang cocok, `stock_type` sengaja
        dibiarkan kosong. Tapi begitu Validate dijalankan barangnya jelas ada --
        quant itulah sumber kebenarannya, dan quant tujuan tidak boleh lahir
        tanpa stock_type.
        """
        picking = self._make_picking(self.type_p2p, self.product_lot, 100.0)
        picking.move_line_ids.unlink()

        pkg_new = self._make_package('UR-PKG-LATE-STOCK')
        line = self._barcode_create_line(
            picking, self.product_lot, 100.0, self.bin_a,
            lot=self.lot_uu, result_package=pkg_new,
        )
        self.assertFalse(line.stock_type, "Prasyarat test: stock_type harus kosong dulu")

        # Barangnya baru muncul sekarang (pallet lain di-unpack ke bin ini).
        pkg_src = self._make_package('UR-PKG-LATE-SRC')
        self._make_quant(self.product_lot, self.bin_a, 100.0, 'UU',
                         lot=self.lot_uu, package=pkg_src)
        self._unpack(pkg_src)

        picking.button_validate()

        quant = self._quants(self.product_lot, self.bin_a,
                             lot=self.lot_uu, package=pkg_new)
        self.assertTrue(quant, "Quant di package baru tidak terbentuk")
        self.assertEqual(
            quant.stock_type, 'UU',
            "Quant tujuan lahir dengan stock_type %r, bukan UU seperti asalnya"
            % quant.stock_type,
        )

    # ==================================================================
    # 4. Bunyi log di chatter pallet
    # ==================================================================
    def _pkg_stock_type_logs(self, package):
        messages = self.env['mail.message'].search([
            ('model', '=', 'stock.package'),
            ('res_id', '=', package.id),
        ], order='id')
        return [
            m.body for m in messages
            if 'Stock Type' in (m.body or '')
        ]

    def test_new_quant_log_says_quant_baru_not_diubah(self):
        """Quant baru: pesannya bukan 'diubah dari [-]'.

        Pindah lokasi selalu melahirkan quant BARU di tujuan, yang lahir tanpa
        stock_type lalu diisi di transaksi yang sama. Itu pencatatan pertama,
        bukan perubahan status barang -- dan di DB dev 78% pesan chatter adalah
        kejadian rutin ini.
        """
        self._make_quant(self.product_lot, self.bin_a, 100.0, 'UU', lot=self.lot_uu)
        picking = self._make_picking(self.type_p2p, self.product_lot, 100.0)

        pkg = self._make_package('UR-PKG-LOG-NEW')
        picking.move_line_ids.write({'result_package_id': pkg.id, 'picked': True})
        picking.button_validate()

        logs = self._pkg_stock_type_logs(pkg)
        self.assertTrue(logs, "Tidak ada log stock_type di chatter pallet")
        self.assertIn('Quant baru terbentuk', logs[-1])
        self.assertIn('[UU]', logs[-1])
        self.assertNotIn('diubah dari [-]', logs[-1])
        self.assertIn(
            'diwarisi dari quant asal', logs[-1],
            "Transfer non-GR: nilainya memang dibaca dari quant sumber, "
            "jadi keterangannya harus ikut tercatat",
        )

    def test_gr_prod_new_quant_log_does_not_claim_inheritance(self):
        """GR produksi: QI-nya dipasang eksplisit, bukan dibaca dari quant.

        `_apply_gr_prod_stock_type()` yang menentukan nilainya, jadi chatter
        tidak boleh mengklaim 'diwarisi dari quant asal' -- di lokasi virtual
        `Production` tidak ada quant asal yang bisa diwarisi.
        """
        # Produk tanpa lot dipakai supaya test ini fokus ke bunyi chatter --
        # penamaan lot GR sudah punya suite sendiri (`wms_gr_lot`).
        picking = self._make_picking(self.type_gr, self.product_plain, 100.0,
                                     src=self.production_loc, dest=self.bin_a)
        picking.move_line_ids.unlink()

        pkg = self._make_package('UR-PKG-LOG-GR')
        line = self._barcode_create_line(
            picking, self.product_plain, 100.0, self.production_loc,
            location_dest=self.bin_a, result_package=pkg,
        )
        self.assertEqual(line.stock_type, 'QI', "Prasyarat: GR harus QI")

        picking.button_validate()
        self.assertEqual(picking.state, 'done')

        logs = self._pkg_stock_type_logs(pkg)
        self.assertTrue(logs, "Tidak ada log stock_type di chatter pallet")
        self.assertIn('Quant baru terbentuk', logs[-1])
        self.assertIn('[QI]', logs[-1])
        self.assertNotIn(
            'diwarisi dari quant asal', logs[-1],
            "GR produksi tidak mewarisi dari quant mana pun, chatter tidak "
            "boleh mengklaim begitu",
        )

    def test_real_change_log_still_says_diubah(self):
        """Perubahan nyata (release/hold) bunyinya tetap seperti dulu."""
        pkg = self._make_package('UR-PKG-LOG-CHANGE')
        quant = self._make_quant(self.product_lot, self.bin_a, 100.0, 'QI',
                                 lot=self.lot_uu, package=pkg)

        quant.write({'stock_type': 'UU'})

        logs = self._pkg_stock_type_logs(pkg)
        self.assertTrue(logs, "Tidak ada log stock_type di chatter pallet")
        self.assertIn('telah diubah dari [QI] menjadi [UU]', logs[-1])

    def test_manual_quant_write_log_does_not_claim_inheritance(self):
        """Penulisan di luar jalur move (adjustment/import) juga netral."""
        pkg = self._make_package('UR-PKG-LOG-MANUAL')
        quant = self._make_quant(self.product_lot, self.bin_a, 50.0, False,
                                 lot=self.lot_uu, package=pkg)

        quant.write({'stock_type': 'UU'})

        logs = self._pkg_stock_type_logs(pkg)
        self.assertTrue(logs, "Tidak ada log stock_type di chatter pallet")
        self.assertIn('Quant baru terbentuk', logs[-1])
        self.assertNotIn('diwarisi dari quant asal', logs[-1])
