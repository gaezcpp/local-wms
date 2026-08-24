from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMatToMat(TransactionCase):
    """Test konversi material lewat mat.to.mat.action_mat_done().

    Fokus utamanya: pallet (stock.package) tidak boleh punya quant negatif
    setelah proses selesai, dan produk hasil konversi harus tetap berada
    di dalam pallet yang sama.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = cls.env.company
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1
        )
        if not cls.warehouse:
            raise ValueError("Butuh minimal satu warehouse untuk company %s" % cls.company.name)

        Location = cls.env['stock.location']
        cls.loc_src = Location.create({
            'name': 'MTM Source Loc',
            'location_id': cls.warehouse.lot_stock_id.id,
            'usage': 'internal',
            'company_id': cls.company.id,
        })
        cls.loc_dst = Location.create({
            'name': 'MTM Dest Loc',
            'location_id': cls.warehouse.lot_stock_id.id,
            'usage': 'internal',
            'company_id': cls.company.id,
        })

        Product = cls.env['product.product']
        cls.product_src = Product.create({
            'name': 'MTM Source Product',
            'default_code': 'MTM-SRC',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'lot',
        })
        cls.product_dst = Product.create({
            'name': 'MTM Dest Product',
            'default_code': 'MTM-DST',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'lot',
        })

        cls.virtual_loc = cls.product_dst.with_company(cls.company).property_stock_inventory
        if not cls.virtual_loc:
            cls.virtual_loc = cls.env['stock.location'].search([
                ('usage', '=', 'inventory'),
                ('company_id', '=', cls.company.id),
                ('barcode', '=', 'ADJUSTMENT'),
            ], limit=1)

        # Matikan jalur recompute beginning stock supaya transfer lot.aft manual
        # yang diuji di sini tidak di-skip.
        cls.env['ir.config_parameter'].sudo().set_param('upload_stock', 'false')

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _make_package(self, name):
        return self.env['stock.package'].create({'name': name})

    def _make_lot(self, name, product):
        return self.env['stock.lot'].create({
            'name': name,
            'product_id': product.id,
            'company_id': self.company.id,
        })

    def _put_stock(self, product, location, qty, lot=None, package=None):
        self.env['stock.quant']._update_available_quantity(
            product, location, qty, lot_id=lot, package_id=package,
        )
        return self.env['stock.quant'].search([
            ('product_id', '=', product.id),
            ('location_id', '=', location.id),
            ('lot_id', '=', lot.id if lot else False),
            ('package_id', '=', package.id if package else False),
        ], limit=1)

    def _make_mtm(self, **overrides):
        vals = {
            'company_id': self.company.id,
            'warehouse_id': self.warehouse.id,
            'warehouse_dest_id': self.warehouse.id,
            'product_id': self.product_src.id,
            'location_id': self.loc_src.id,
            'product_dest_id': self.product_dst.id,
            'location_dest_id': self.loc_dst.id,
        }
        vals.update(overrides)
        return self.env['mat.to.mat'].create(vals)

    def _run_to_done(self, mtm):
        mtm.action_check_availibility()
        mtm.mat_source_ids.write({'is_selected': True})
        mtm.action_mat_ready()
        mtm.action_mat_done()
        return mtm

    def _moves_of(self, mtm):
        return self.env['stock.move'].search([('origin', '=', mtm.name)], order='id')

    # ------------------------------------------------------------------
    # tests
    # ------------------------------------------------------------------
    def test_01_no_negative_quant_in_package(self):
        """Regresi utama: tidak boleh ada quant minus yang menempel di pallet."""
        package = self._make_package('MTM-PKG-01')
        lot = self._make_lot('MTM-LOT-01', self.product_src)
        self._put_stock(self.product_src, self.loc_src, 100.0, lot=lot, package=package)

        mtm = self._run_to_done(self._make_mtm())
        self.assertEqual(mtm.state, 'done')

        negatives = package.contained_quant_ids.filtered(lambda q: q.quantity < 0)
        self.assertFalse(
            negatives,
            "Pallet punya quant negatif: %s" % negatives.mapped(
                lambda q: (q.product_id.default_code, q.location_id.complete_name, q.quantity)
            ),
        )

        # Tidak boleh ada sisa quant berpallet di lokasi virtual production
        stuck = self.env['stock.quant'].search([
            ('package_id', '=', package.id),
            ('location_id', '=', self.virtual_loc.id),
        ])
        self.assertFalse(stuck, "Masih ada quant berpallet di lokasi virtual production")

    def test_02_stock_moved_to_dest_product_in_same_package(self):
        """Produk tujuan harus ada di lokasi tujuan DAN tetap di dalam pallet."""
        package = self._make_package('MTM-PKG-02')
        lot = self._make_lot('MTM-LOT-02', self.product_src)
        self._put_stock(self.product_src, self.loc_src, 80.0, lot=lot, package=package)

        self._run_to_done(self._make_mtm())

        dest_quant = self.env['stock.quant'].search([
            ('product_id', '=', self.product_dst.id),
            ('location_id', '=', self.loc_dst.id),
            ('package_id', '=', package.id),
        ])
        self.assertEqual(len(dest_quant), 1, "Quant tujuan harus tepat satu")
        self.assertEqual(dest_quant.quantity, 80.0)
        self.assertEqual(dest_quant.lot_id.name, 'MTM-LOT-02')
        self.assertEqual(dest_quant.lot_id.product_id, self.product_dst)

        src_qty = sum(self.env['stock.quant'].search([
            ('product_id', '=', self.product_src.id),
            ('location_id', '=', self.loc_src.id),
        ]).mapped('quantity'))
        self.assertEqual(src_qty, 0.0, "Stok produk sumber harus habis")

        self.assertEqual(package.location_id, self.loc_dst)

    def test_03_move_line_package_fields(self):
        """Outward: package_id terisi / result_package_id kosong.
        Inward: kebalikannya. Ini akar bug quant negatif."""
        package = self._make_package('MTM-PKG-03')
        lot = self._make_lot('MTM-LOT-03', self.product_src)
        self._put_stock(self.product_src, self.loc_src, 50.0, lot=lot, package=package)

        mtm = self._run_to_done(self._make_mtm())

        moves = self._moves_of(mtm)
        self.assertEqual(len(moves), 2, "Harus ada 2 move: outward dan inward")

        move_out = moves.filtered(lambda m: m.location_dest_id == self.virtual_loc)
        move_in = moves.filtered(lambda m: m.location_id == self.virtual_loc)
        self.assertEqual(len(move_out), 1)
        self.assertEqual(len(move_in), 1)
        self.assertEqual(move_out.state, 'done')
        self.assertEqual(move_in.state, 'done')

        ml_out = move_out.move_line_ids
        self.assertEqual(ml_out.package_id, package)
        self.assertFalse(ml_out.result_package_id)

        ml_in = move_in.move_line_ids
        self.assertFalse(
            ml_in.package_id,
            "Move line inward tidak boleh punya package_id, itu yang bikin quant minus",
        )
        self.assertEqual(ml_in.result_package_id, package)

    def test_17_reference_and_origin_carry_document_name(self):
        """reference & origin di move + move line harus terisi nomor dokumen.

        stock.move.line.reference itu related non-stored ke stock.move.reference,
        dan stock.move.reference adalah stored compute yang defaultnya picking_id.name.
        Move di sini tidak punya picking, jadi nilainya harus benar-benar dicek
        bertahan setelah _action_done() dan setelah cache di-invalidate.
        """
        package = self._make_package('MTM-PKG-17')
        lot = self._make_lot('MTM-LOT-17', self.product_src)
        self._put_stock(self.product_src, self.loc_src, 45.0, lot=lot, package=package)

        mtm = self._run_to_done(self._make_mtm())

        moves = self._moves_of(mtm)
        self.assertEqual(len(moves), 2)

        # Baca ulang dari DB, bukan dari cache
        moves.invalidate_recordset()
        for move in moves:
            self.assertEqual(
                move.reference, mtm.name,
                "stock.move.reference ketimpa ulang oleh _compute_reference",
            )
            self.assertEqual(move.origin, mtm.name)

        move_lines = moves.move_line_ids
        self.assertEqual(len(move_lines), 2)
        move_lines.invalidate_recordset()
        for ml in move_lines:
            self.assertEqual(ml.reference, mtm.name)
            self.assertEqual(ml.origin, mtm.name)
            self.assertEqual(ml.state, 'done')

    def test_04_custom_quant_fields_are_synced(self):
        """Field kustom stock.quant ikut pindah ke quant tujuan."""
        package = self._make_package('MTM-PKG-04')
        lot = self._make_lot('MTM-LOT-04', self.product_src)
        src_quant = self._put_stock(
            self.product_src, self.loc_src, 60.0, lot=lot, package=package
        )
        src_quant.write({'stock_type': 'UU', 'bag_qty': 30.0})

        mtm = self._run_to_done(self._make_mtm())

        dest_quant = self.env['stock.quant'].search([
            ('product_id', '=', self.product_dst.id),
            ('location_id', '=', self.loc_dst.id),
            ('package_id', '=', package.id),
        ], limit=1)
        self.assertTrue(dest_quant)
        self.assertEqual(dest_quant.stock_type, 'UU')
        self.assertEqual(dest_quant.bag_qty, 30.0)

        dest_line = mtm.mat_destination_ids
        self.assertEqual(len(dest_line), 1)
        self.assertEqual(dest_line.quant_id, dest_quant)
        self.assertEqual(dest_line.package_id, package)
        self.assertEqual(dest_line.stock_type, 'UU')

    def test_05_lot_aft_balance_is_transferred(self):
        """Saldo stock.lot.aft pindah dari lot sumber ke lot tujuan."""
        package = self._make_package('MTM-PKG-05')
        lot = self._make_lot('MTM-LOT-05', self.product_src)
        src_quant = self._put_stock(
            self.product_src, self.loc_src, 100.0, lot=lot, package=package
        )
        src_quant.write({'stock_type': 'UU', 'bag_qty': 50.0})

        src_aft = self.env['stock.lot.aft'].create({
            'lot_id': lot.id,
            'stock_type': 'UU',
            'quantity': 100.0,
            'bag_qty': 50.0,
            'uom_id': self.product_src.uom_id.id,
        })

        self._run_to_done(self._make_mtm())

        self.assertEqual(src_aft.quantity, 0.0, "Saldo lot.aft sumber harus berkurang")
        self.assertEqual(src_aft.bag_qty, 0.0)

        dest_lot = self.env['stock.lot'].search([
            ('name', '=', 'MTM-LOT-05'),
            ('product_id', '=', self.product_dst.id),
        ], limit=1)
        self.assertTrue(dest_lot, "Lot tujuan harus dibuat")

        dest_aft = self.env['stock.lot.aft'].search([
            ('lot_id', '=', dest_lot.id),
            ('stock_type', '=', 'UU'),
        ])
        self.assertEqual(len(dest_aft), 1)
        self.assertEqual(dest_aft.quantity, 100.0)
        self.assertEqual(dest_aft.bag_qty, 50.0)

    def test_06_dest_lot_inherits_source_lot_fields(self):
        """Lot tujuan mewarisi atribut lot sumber."""
        package = self._make_package('MTM-PKG-06')
        lot = self._make_lot('MTM-LOT-06', self.product_src)
        lot.write({'ref': 'REF-ASAL'})
        self._put_stock(self.product_src, self.loc_src, 40.0, lot=lot, package=package)

        self._run_to_done(self._make_mtm())

        dest_lot = self.env['stock.lot'].search([
            ('name', '=', 'MTM-LOT-06'),
            ('product_id', '=', self.product_dst.id),
        ], limit=1)
        self.assertTrue(dest_lot)
        self.assertEqual(dest_lot.ref, 'REF-ASAL')

    def test_07_shortage_is_blocked(self):
        """Stok sumber berkurang setelah Ready -> Done harus ditolak, bukan bikin minus."""
        package = self._make_package('MTM-PKG-07')
        lot = self._make_lot('MTM-LOT-07', self.product_src)
        self._put_stock(self.product_src, self.loc_src, 100.0, lot=lot, package=package)

        mtm = self._make_mtm()
        mtm.action_check_availibility()
        mtm.mat_source_ids.write({'is_selected': True})
        mtm.action_mat_ready()

        # Simulasi stok keburu dipakai dokumen lain
        self.env['stock.quant']._update_available_quantity(
            self.product_src, self.loc_src, -70.0, lot_id=lot, package_id=package,
        )

        with self.assertRaises(ValidationError):
            mtm.action_mat_done()

        self.assertEqual(mtm.state, 'ready', "Dokumen harus tetap di Ready")
        negatives = package.contained_quant_ids.filtered(lambda q: q.quantity < 0)
        self.assertFalse(negatives)

    def test_08_partial_selection_keeps_rest_of_pallet(self):
        """Hanya line yang dipilih yang dikonversi; pallet lain tidak tersentuh."""
        package_a = self._make_package('MTM-PKG-08A')
        package_b = self._make_package('MTM-PKG-08B')
        lot_a = self._make_lot('MTM-LOT-08A', self.product_src)
        lot_b = self._make_lot('MTM-LOT-08B', self.product_src)
        self._put_stock(self.product_src, self.loc_src, 30.0, lot=lot_a, package=package_a)
        self._put_stock(self.product_src, self.loc_src, 45.0, lot=lot_b, package=package_b)

        mtm = self._make_mtm()
        mtm.action_check_availibility()
        self.assertEqual(len(mtm.mat_source_ids), 2)

        line_a = mtm.mat_source_ids.filtered(lambda l: l.package_id == package_a)
        line_a.write({'is_selected': True})
        mtm.action_mat_ready()
        mtm.action_mat_done()

        # Pallet A dikonversi
        self.assertFalse(package_a.contained_quant_ids.filtered(lambda q: q.quantity < 0))
        dest_a = self.env['stock.quant'].search([
            ('product_id', '=', self.product_dst.id),
            ('package_id', '=', package_a.id),
        ])
        self.assertEqual(sum(dest_a.mapped('quantity')), 30.0)

        # Pallet B tidak tersentuh
        remaining_b = self.env['stock.quant'].search([
            ('product_id', '=', self.product_src.id),
            ('package_id', '=', package_b.id),
        ])
        self.assertEqual(sum(remaining_b.mapped('quantity')), 45.0)
        self.assertFalse(self.env['stock.quant'].search([
            ('product_id', '=', self.product_dst.id),
            ('package_id', '=', package_b.id),
        ]))

    def test_09_multiple_lines_same_document(self):
        """Beberapa pallet dikonversi dalam satu dokumen."""
        packages = [self._make_package('MTM-PKG-09-%s' % i) for i in range(3)]
        for idx, pkg in enumerate(packages):
            lot = self._make_lot('MTM-LOT-09-%s' % idx, self.product_src)
            self._put_stock(self.product_src, self.loc_src, 10.0 * (idx + 1), lot=lot, package=pkg)

        mtm = self._run_to_done(self._make_mtm())

        moves = self._moves_of(mtm)
        self.assertEqual(len(moves), 6, "3 line x (outward + inward)")

        for idx, pkg in enumerate(packages):
            self.assertFalse(
                pkg.contained_quant_ids.filtered(lambda q: q.quantity < 0),
                "Pallet %s punya quant negatif" % pkg.name,
            )
            dest = self.env['stock.quant'].search([
                ('product_id', '=', self.product_dst.id),
                ('package_id', '=', pkg.id),
            ])
            self.assertEqual(sum(dest.mapped('quantity')), 10.0 * (idx + 1))

        self.assertEqual(len(mtm.mat_destination_ids), 3)

    def test_14_empty_dest_location_stays_in_source_location(self):
        """Destination Location kosong + warehouse sama -> barang tetap di lokasi source."""
        package = self._make_package('MTM-PKG-14')
        lot = self._make_lot('MTM-LOT-14', self.product_src)
        self._put_stock(self.product_src, self.loc_src, 35.0, lot=lot, package=package)

        mtm = self._make_mtm(location_dest_id=False)
        self._run_to_done(mtm)
        self.assertEqual(mtm.state, 'done')

        # Barang jadi ada di lokasi ASAL, bukan di lokasi lain
        dest_quant = self.env['stock.quant'].search([
            ('product_id', '=', self.product_dst.id),
            ('location_id', '=', self.loc_src.id),
            ('package_id', '=', package.id),
        ])
        self.assertEqual(len(dest_quant), 1)
        self.assertEqual(dest_quant.quantity, 35.0)

        # Tidak ada yang nyasar ke loc_dst
        self.assertFalse(self.env['stock.quant'].search([
            ('product_id', '=', self.product_dst.id),
            ('location_id', '=', self.loc_dst.id),
        ]))
        self.assertFalse(package.contained_quant_ids.filtered(lambda q: q.quantity < 0))
        self.assertEqual(package.location_id, self.loc_src)

        # Tab Destination dan counter tetap benar tanpa location_dest_id
        self.assertEqual(len(mtm.mat_destination_ids), 1)
        self.assertEqual(mtm.mat_destination_ids.location_id, self.loc_src)
        self.assertEqual(mtm.mat_destination_ids.quant_id, dest_quant)
        mtm.invalidate_recordset()
        self.assertGreaterEqual(mtm.quant_count, 1)
        action = mtm.action_view_stock_quants()
        self.assertTrue(self.env['stock.quant'].search(action['domain']))

    def test_15_empty_dest_location_multi_source_locations(self):
        """Tanpa Destination Location, tiap line kembali ke lokasinya masing-masing."""
        loc_src2 = self.env['stock.location'].create({
            'name': 'MTM Source Loc 2',
            'location_id': self.warehouse.lot_stock_id.id,
            'usage': 'internal',
            'company_id': self.company.id,
        })
        pkg1 = self._make_package('MTM-PKG-15A')
        pkg2 = self._make_package('MTM-PKG-15B')
        lot1 = self._make_lot('MTM-LOT-15A', self.product_src)
        lot2 = self._make_lot('MTM-LOT-15B', self.product_src)
        self._put_stock(self.product_src, self.loc_src, 10.0, lot=lot1, package=pkg1)
        self._put_stock(self.product_src, loc_src2, 20.0, lot=lot2, package=pkg2)

        # location_id dikosongkan supaya kedua lokasi ikut terjaring
        mtm = self._make_mtm(location_id=False, location_dest_id=False)
        self._run_to_done(mtm)

        q1 = self.env['stock.quant'].search([
            ('product_id', '=', self.product_dst.id), ('package_id', '=', pkg1.id),
        ])
        q2 = self.env['stock.quant'].search([
            ('product_id', '=', self.product_dst.id), ('package_id', '=', pkg2.id),
        ])
        self.assertEqual(q1.location_id, self.loc_src)
        self.assertEqual(q1.quantity, 10.0)
        self.assertEqual(q2.location_id, loc_src2)
        self.assertEqual(q2.quantity, 20.0)

        for pkg in (pkg1, pkg2):
            self.assertFalse(pkg.contained_quant_ids.filtered(lambda q: q.quantity < 0))

    def test_16_diff_warehouse_requires_dest_location(self):
        """Beda warehouse tanpa Destination Location harus ditolak, bukan error ORM."""
        wh2 = self.env['stock.warehouse'].create({
            'name': 'MTM Warehouse 3',
            'code': 'MTM3',
            'company_id': self.company.id,
        })
        package = self._make_package('MTM-PKG-16')
        lot = self._make_lot('MTM-LOT-16', self.product_src)
        self._put_stock(self.product_src, self.loc_src, 5.0, lot=lot, package=package)

        mtm = self._make_mtm(warehouse_dest_id=wh2.id, location_dest_id=False)
        mtm.action_check_availibility()
        mtm.mat_source_ids.write({'is_selected': True})

        # Ditolak sejak tombol Ready
        with self.assertRaises(ValidationError):
            mtm.action_mat_ready()
        self.assertEqual(mtm.state, 'draft')

        # Pengaman kedua di action_mat_done, kalau state di-set lewat jalur lain
        mtm.write({'state': 'ready'})
        with self.assertRaises(ValidationError):
            mtm.action_mat_done()
        self.assertFalse(self.env['stock.move'].search([('origin', '=', mtm.name)]))

    def test_12_smart_button_counters(self):
        """Counter smart button (dipakai compute non-stored di form) tidak boleh error."""
        package = self._make_package('MTM-PKG-12')
        lot = self._make_lot('MTM-LOT-12', self.product_src)
        self._put_stock(self.product_src, self.loc_src, 15.0, lot=lot, package=package)

        mtm = self._run_to_done(self._make_mtm())
        mtm.invalidate_recordset()

        self.assertEqual(mtm.move_count, 2)
        self.assertEqual(mtm.move_line_count, 2)
        self.assertGreaterEqual(mtm.quant_count, 1)

        # Action smart button juga harus mengembalikan domain yang valid
        for action in (
            mtm.action_view_stock_moves(),
            mtm.action_view_stock_move_lines(),
            mtm.action_view_stock_quants(),
        ):
            self.assertEqual(action['type'], 'ir.actions.act_window')
            self.assertTrue(self.env[action['res_model']].search(action['domain']))

    def test_13_cancel_clears_lines(self):
        """Cancel dari Ready mengosongkan tab Source & Destination."""
        package = self._make_package('MTM-PKG-13')
        lot = self._make_lot('MTM-LOT-13', self.product_src)
        self._put_stock(self.product_src, self.loc_src, 12.0, lot=lot, package=package)

        mtm = self._make_mtm()
        mtm.action_check_availibility()
        mtm.mat_source_ids.write({'is_selected': True})
        mtm.action_mat_ready()
        mtm.action_mat_cancel()

        self.assertEqual(mtm.state, 'cancel')
        self.assertFalse(mtm.mat_source_ids)
        self.assertFalse(mtm.mat_destination_ids)
        # Stok tidak boleh tersentuh sama sekali
        self.assertEqual(sum(package.contained_quant_ids.mapped('quantity')), 12.0)

    def test_11_diff_warehouse_creates_internal_transfer(self):
        """Beda warehouse: barang jadi di lokasi asal + dibuatkan internal transfer
        yang tetap membawa pallet-nya (result_package_id terisi)."""
        wh2 = self.env['stock.warehouse'].create({
            'name': 'MTM Warehouse 2',
            'code': 'MTM2',
            'company_id': self.company.id,
        })

        package = self._make_package('MTM-PKG-11')
        lot = self._make_lot('MTM-LOT-11', self.product_src)
        self._put_stock(self.product_src, self.loc_src, 20.0, lot=lot, package=package)

        mtm = self._make_mtm(
            warehouse_dest_id=wh2.id,
            location_dest_id=wh2.lot_stock_id.id,
        )
        self._run_to_done(mtm)

        self.assertFalse(package.contained_quant_ids.filtered(lambda q: q.quantity < 0))

        # Barang jadi masih di lokasi asal, menunggu transfer
        staged = self.env['stock.quant'].search([
            ('product_id', '=', self.product_dst.id),
            ('location_id', '=', self.loc_src.id),
            ('package_id', '=', package.id),
        ])
        self.assertEqual(sum(staged.mapped('quantity')), 20.0)

        self.assertTrue(mtm.picking_id, "Internal transfer harus dibuat")
        self.assertEqual(mtm.picking_id.location_dest_id, wh2.lot_stock_id)
        self.assertEqual(mtm.picking_id.state, 'assigned')

        transfer_lines = mtm.picking_id.move_line_ids
        self.assertTrue(transfer_lines, "Internal transfer harus sudah ter-reserve")
        for ml in transfer_lines:
            self.assertEqual(ml.package_id, package)
            self.assertEqual(
                ml.result_package_id, package,
                "Pallet harus ikut pindah utuh, bukan dibongkar saat validasi",
            )

    def test_10_without_package(self):
        """Stok tanpa pallet tetap bisa dikonversi."""
        lot = self._make_lot('MTM-LOT-10', self.product_src)
        self._put_stock(self.product_src, self.loc_src, 25.0, lot=lot)

        mtm = self._run_to_done(self._make_mtm())
        self.assertEqual(mtm.state, 'done')

        dest = self.env['stock.quant'].search([
            ('product_id', '=', self.product_dst.id),
            ('location_id', '=', self.loc_dst.id),
            ('package_id', '=', False),
        ])
        self.assertEqual(sum(dest.mapped('quantity')), 25.0)
