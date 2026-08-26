"""Unit test proses outbound company 1601 (company_id = 2) lewat Barcode.

Fokus skenario: **satu lot yang sama tersebar di beberapa pallet, tapi tiap
pallet berasal dari production line (production code) yang berbeda.**

Ini bisa terjadi karena format Production Code company 2 hanya memakai
`prod_code` satu digit (lihat `production.code` id 1), sedangkan beberapa
`production.line` berbagi `prod_code` yang sama — mis. line `CPM10` (10) dan
`CPM11` (11) sama-sama ber-`prod_code` '1', `CPM9` (09), `LINE AYAKS` (93) dan
`CPM9-MHW` (94) sama-sama '9'. Hasilnya satu `stock.lot` memuat barang dari
lebih dari satu production line, dan pembedanya cuma `production_line_id` +
`pallet_ke` di quant/pallet-nya.

Rantai yang diuji mengikuti konfigurasi operation type yang aktif sekarang:

    [FINI/1601] -> (PICK)  Pick         -> [FINI/STG - OUT]
                -> (CO)    Checker Out  -> [FINI/STG - OUT Checker Out]
                -> (LOAD)  Loading      -> [FINI/Gate Out]

Semua test memakai `TransactionCase`, jadi data uji di-rollback dan database
dev tidak berubah.
"""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'wms_outbound')
class TestOutboundBarcodeMultiProductionLine(TransactionCase):

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

        PickingType = cls.env['stock.picking.type']
        cls.type_pick = PickingType.search([
            ('company_id', '=', cls.company.id),
            ('sequence_code', '=', 'PICK'),
            ('uu_only', '=', True),
        ], limit=1)
        cls.type_co = PickingType.search([
            ('company_id', '=', cls.company.id),
            ('sequence_code', '=', 'CO'),
        ], limit=1)
        cls.type_load = PickingType.search([
            ('company_id', '=', cls.company.id),
            ('sequence_code', '=', 'LOAD'),
        ], limit=1)
        for name, ptype in (('PICK', cls.type_pick), ('CO', cls.type_co), ('LOAD', cls.type_load)):
            if not ptype:
                raise ValueError("Operation type %s untuk company %s tidak ditemukan." % (name, cls.company.name))

        cls.loc_stock = cls.type_pick.default_location_src_id
        cls.loc_stg_out = cls.type_pick.default_location_dest_id
        cls.loc_checker_out = cls.type_co.default_location_dest_id
        cls.loc_gate_out = cls.type_load.default_location_dest_id

        # Sub-lokasi bin di dalam FINI/1601, seperti kondisi nyata (D1/1/03 dst).
        cls.loc_bin = cls.env['stock.location'].create({
            'name': 'UT-BIN-01',
            'location_id': cls.loc_stock.id,
            'usage': 'internal',
            'company_id': cls.company.id,
        })

        # Ambil konfigurasi UoM (KG / BAG / Pallet) dari produk nyata company ini
        # supaya konversi bag_qty & pallet_qty ikut terkena uji.
        reference = cls.env['product.product'].search([
            ('uom_bag_id', '!=', False),
            ('uom_pallet_id', '!=', False),
            ('tracking', '=', 'lot'),
        ], limit=1)
        if not reference:
            raise ValueError("Tidak ada produk dengan UoM Bag & Pallet untuk dijadikan acuan.")

        cls.product = cls.env['product.product'].create({
            'name': 'UT Outbound Multi Prodline',
            'default_code': 'UT-OUT-MPL',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'lot',
            'uom_id': reference.uom_id.id,
            'uom_bag_id': reference.uom_bag_id.id,
            'uom_pallet_id': reference.uom_pallet_id.id,
        })

        # Dua production line berbeda yang menghasilkan nama lot identik.
        ProductionLine = cls.env['production.line']
        cls.line_a, cls.line_b = ProductionLine.search([
            ('company_id', '=', cls.company.id),
        ], limit=2)
        if not cls.line_b:
            raise ValueError("Butuh minimal dua production.line pada company ini.")

        # Satu lot dipakai bersama oleh kedua production line.
        cls.lot = cls.env['stock.lot'].create({
            'name': 'UT-LOT-SHARED-9',
            'product_id': cls.product.id,
            'company_id': cls.company.id,
        })

        cls.qty_per_pallet = 1280.0

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _make_pallet(self, name, production_line, qty=None, location=None):
        """Buat satu pallet berisi `qty` produk dari `production_line`."""
        qty = self.qty_per_pallet if qty is None else qty
        location = location or self.loc_bin
        package = self.env['stock.package'].create({
            'name': name,
            'company_id': self.company.id,
        })
        package.yellow_tag = 'ready'
        self.env['stock.quant']._update_available_quantity(
            self.product, location, qty, lot_id=self.lot, package_id=package,
        )
        quant = self.env['stock.quant'].sudo().search([
            ('product_id', '=', self.product.id),
            ('location_id', '=', location.id),
            ('lot_id', '=', self.lot.id),
            ('package_id', '=', package.id),
        ], limit=1)
        quant.write({
            'stock_type': 'UU',
            'production_line_id': production_line.id,
        })
        return package, quant

    def _make_bulk_quant(self, production_line, qty=None, location=None):
        """Quant tanpa pallet — sengaja dipakai untuk menguji konsolidasi SML."""
        qty = self.qty_per_pallet if qty is None else qty
        location = location or self.loc_bin
        self.env['stock.quant']._update_available_quantity(
            self.product, location, qty, lot_id=self.lot,
        )
        quant = self.env['stock.quant'].sudo().search([
            ('product_id', '=', self.product.id),
            ('location_id', '=', location.id),
            ('lot_id', '=', self.lot.id),
            ('package_id', '=', False),
        ], limit=1)
        quant.write({'stock_type': 'UU', 'production_line_id': production_line.id})
        return quant

    def _make_picking(self, picking_type, qty, location=None, location_dest=None,
                      move_orig=None, procure_method='make_to_stock'):
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': (location or picking_type.default_location_src_id).id,
            'location_dest_id': (location_dest or picking_type.default_location_dest_id).id,
            'company_id': self.company.id,
        })
        move_vals = {
            'picking_id': picking.id,
            'product_id': self.product.id,
            'product_uom_qty': qty,
            'product_uom': self.product.uom_id.id,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
            'company_id': self.company.id,
            'procure_method': procure_method,
        }
        if move_orig:
            move_vals['move_orig_ids'] = [(6, 0, move_orig.ids)]
        self.env['stock.move'].create(move_vals)
        picking.action_confirm()
        return picking

    def _scan(self, picking, commands):
        """Tiru controller `/stock_barcode/save_barcode_data`.

        Client barcode menyimpan hasil scan persis lewat
        `picking.write({'move_line_ids': commands})`, jadi jalur create/write
        custom di `stock.move.line` ikut teruji.
        """
        picking.write({'move_line_ids': commands})
        return picking._get_stock_barcode_data()

    def _scan_new_line_vals(self, picking, package, qty):
        """Nilai yang dikirim client saat operator scan satu pallet baru."""
        return {
            'picking_id': picking.id,
            'product_id': self.product.id,
            'product_uom_id': self.product.uom_id.id,
            'location_id': package.location_id.id or self.loc_bin.id,
            'location_dest_id': picking.location_dest_id.id,
            'lot_id': self.lot.id,
            'package_id': package.id,
            'result_package_id': package.id,
            'owner_id': False,
            'quantity': qty,
            'picked': True,
            'state': 'assigned',
        }

    def _line_prodline(self, line):
        return line.production_line_id

    def _validate(self, picking):
        res = picking.button_validate()
        self.assertNotIsInstance(
            res, dict,
            "button_validate %s minta wizard tambahan: %s" % (picking.name, res),
        )
        self.assertEqual(picking.state, 'done')
        return res

    # ------------------------------------------------------------------
    # 1. Reservasi PICK
    # ------------------------------------------------------------------
    def test_01_pick_reserve_keeps_production_line_per_pallet(self):
        """PICK harus membawa production line tiap pallet ke move line-nya.

        Tanpa itu, kode produksi hilang sejak langkah pertama outbound dan
        semua langkah sesudahnya (CO, LOAD) ikut kosong.
        """
        pkg_a, _ = self._make_pallet('UT-PLT-A', self.line_a)
        pkg_b, _ = self._make_pallet('UT-PLT-B', self.line_b)

        picking = self._make_picking(self.type_pick, self.qty_per_pallet * 2)
        picking.action_assign()

        lines = picking.move_line_ids
        self.assertEqual(len(lines), 2, "Harus ada satu move line per pallet.")

        by_package = {line.package_id: line for line in lines}
        self.assertEqual(set(by_package), {pkg_a, pkg_b})
        self.assertEqual(
            by_package[pkg_a].production_line_id, self.line_a,
            "Move line pallet A kehilangan production line dari quant-nya.",
        )
        self.assertEqual(
            by_package[pkg_b].production_line_id, self.line_b,
            "Move line pallet B kehilangan production line dari quant-nya.",
        )
        self.assertEqual(set(lines.mapped('stock_type')), {'UU'})

    def test_02_pick_reserve_keeps_pallet_ke_per_pallet(self):
        """`pallet_ke` tiap pallet juga harus ikut ke move line."""
        pkg_a, quant_a = self._make_pallet('UT-PLT-A', self.line_a)
        pkg_b, quant_b = self._make_pallet('UT-PLT-B', self.line_b)
        quant_a.write({'pallet_ke': 15})
        quant_b.write({'pallet_ke': 1})

        picking = self._make_picking(self.type_pick, self.qty_per_pallet * 2)
        picking.action_assign()

        by_package = {line.package_id: line for line in picking.move_line_ids}
        self.assertEqual(by_package[pkg_a].pallet_ke, 15)
        self.assertEqual(by_package[pkg_b].pallet_ke, 1)

    # ------------------------------------------------------------------
    # 2. Konsolidasi move line
    # ------------------------------------------------------------------
    def test_03_consolidate_does_not_merge_different_production_line(self):
        """Dua quant curah (tanpa pallet) satu lot beda production line.

        `_consolidate_sml_per_quant()` mengelompokkan move line dengan kunci
        (move, location, lot, package, owner) — production line tidak ikut, jadi
        dua baris beda kode produksi berisiko dilebur jadi satu.
        """
        self._make_bulk_quant(self.line_a, qty=500.0)
        # Quant kedua di lokasi berbeda supaya benar-benar jadi dua quant
        # dengan lot sama namun production line berbeda.
        loc_bin_2 = self.env['stock.location'].create({
            'name': 'UT-BIN-02',
            'location_id': self.loc_stock.id,
            'usage': 'internal',
            'company_id': self.company.id,
        })
        self._make_bulk_quant(self.line_b, qty=500.0, location=loc_bin_2)

        # PICK company ini uu_only -> hanya ambil quant ber-pallet, jadi untuk
        # kasus curah dipakai operation type internal biasa (Bin to Bin).
        type_int = self.env['stock.picking.type'].search([
            ('company_id', '=', self.company.id),
            ('code', '=', 'internal'),
            ('uu_only', '=', False),
            ('sequence_code', '=', 'INT'),
        ], limit=1)
        picking = self._make_picking(
            type_int, 1000.0,
            location=self.loc_stock, location_dest=self.loc_stg_out,
        )
        picking.action_assign()

        lines = picking.move_line_ids
        self.assertEqual(
            len(lines), 2,
            "Dua quant beda production line dilebur jadi satu move line — "
            "kode produksi per quantity hilang.",
        )
        self.assertEqual(
            set(lines.mapped('production_line_id')), {self.line_a, self.line_b},
        )

    # ------------------------------------------------------------------
    # 3. Scan barcode di PICK
    # ------------------------------------------------------------------
    def test_04_barcode_scan_two_pallets_same_lot(self):
        """Operator scan dua pallet berisi lot yang sama lewat client barcode."""
        pkg_a, _ = self._make_pallet('UT-PLT-A', self.line_a)
        pkg_b, _ = self._make_pallet('UT-PLT-B', self.line_b)

        picking = self._make_picking(self.type_pick, self.qty_per_pallet * 2)
        picking.action_assign()
        picking.move_line_ids.unlink()

        self._scan(picking, [
            (0, 0, self._scan_new_line_vals(picking, pkg_a, self.qty_per_pallet)),
            (0, 0, self._scan_new_line_vals(picking, pkg_b, self.qty_per_pallet)),
        ])

        lines = picking.move_line_ids
        self.assertEqual(len(lines), 2, "Hasil scan dua pallet harus jadi dua move line.")
        self.assertEqual(
            sum(lines.mapped('quantity')), self.qty_per_pallet * 2,
            "Total hasil scan tidak sama dengan yang dipindai.",
        )
        by_package = {line.package_id: line for line in lines}
        self.assertEqual(by_package[pkg_a].production_line_id, self.line_a)
        self.assertEqual(by_package[pkg_b].production_line_id, self.line_b)

    # ------------------------------------------------------------------
    # 4. Rantai penuh PICK -> CO -> LOAD
    # ------------------------------------------------------------------
    def test_05_full_chain_pick_co_load(self):
        """Kode produksi tiap pallet harus utuh sampai Loading."""
        pkg_a, _ = self._make_pallet('UT-PLT-A', self.line_a)
        pkg_b, _ = self._make_pallet('UT-PLT-B', self.line_b)
        total = self.qty_per_pallet * 2

        pick = self._make_picking(self.type_pick, total)
        pick.action_assign()
        self.assertEqual(pick.state, 'assigned')
        self._validate(pick)

        # Quant hasil PICK di STG - OUT harus tetap membawa production line.
        quants = self.env['stock.quant'].sudo().search([
            ('product_id', '=', self.product.id),
            ('location_id', '=', self.loc_stg_out.id),
            ('lot_id', '=', self.lot.id),
        ])
        self.assertEqual(
            {q.package_id: q.production_line_id for q in quants},
            {pkg_a: self.line_a, pkg_b: self.line_b},
            "Production line hilang dari quant setelah PICK divalidasi.",
        )

        co = self._make_picking(
            self.type_co, total,
            move_orig=pick.move_ids, procure_method='make_to_order',
        )
        co.action_assign()
        self.assertEqual(co.state, 'assigned')
        by_package = {line.package_id: line for line in co.move_line_ids}
        self.assertEqual(
            by_package[pkg_a].production_line_id, self.line_a,
            "Checker Out menaruh production line yang salah pada pallet A.",
        )
        self.assertEqual(
            by_package[pkg_b].production_line_id, self.line_b,
            "Checker Out menaruh production line yang salah pada pallet B.",
        )
        co.move_line_ids.write({'result_package_id': False})
        for line in co.move_line_ids:
            line.result_package_id = line.package_id
        self._validate(co)

        load = self._make_picking(
            self.type_load, total,
            move_orig=co.move_ids, procure_method='make_to_order',
        )
        load.action_assign()
        self.assertEqual(load.state, 'assigned')
        by_package = {line.package_id: line for line in load.move_line_ids}
        self.assertEqual(
            by_package[pkg_a].production_line_id, self.line_a,
            "Loading menaruh production line yang salah pada pallet A.",
        )
        self.assertEqual(
            by_package[pkg_b].production_line_id, self.line_b,
            "Loading menaruh production line yang salah pada pallet B.",
        )

    # ------------------------------------------------------------------
    # 5. Partial pick dari pallet yang sama
    # ------------------------------------------------------------------
    def test_06_partial_pick_two_pallets_same_lot(self):
        """Ambil sebagian dari tiap pallet — sisa reservasi tidak boleh bocor."""
        pkg_a, quant_a = self._make_pallet('UT-PLT-A', self.line_a)
        pkg_b, quant_b = self._make_pallet('UT-PLT-B', self.line_b)

        picking = self._make_picking(self.type_pick, 1500.0)
        picking.action_assign()

        lines = picking.move_line_ids
        self.assertEqual(sum(lines.mapped('quantity')), 1500.0)
        self.assertEqual(
            quant_a.reserved_quantity + quant_b.reserved_quantity, 1500.0,
            "Reservasi quant tidak sama dengan quantity move line.",
        )
        for line in lines:
            quant = quant_a if line.package_id == pkg_a else quant_b
            self.assertEqual(
                line.production_line_id, quant.production_line_id,
                "Move line %s memakai production line dari pallet lain." % line.id,
            )
