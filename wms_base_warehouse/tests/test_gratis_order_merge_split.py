"""Uji rangkaian "gratis" (barang cuma-cuma) pada `sale.order.line` sepanjang
rantai outbound company 1601 (`company_id=2`), memakai konfigurasi picking
type/route ASLI (route `1601 - SO Loco 909`, channel Loco Unaffiliated):

    [FINI/1601] -> (PICK)  Pick               -> [FINI/STG - OUT]
                -> (CO)    Checker Out        -> [FINI/STG - OUT Checker Out]
                -> (LOAD)  Loading            -> [FINI/Gate Out]
                -> (LC-FINAL, move_type_sap=909)  Loco - Final - Unaffiliated -> [FINI/Gate Out/Done]

Fokus: `stock.move._action_confirm()`/`_merge_gratis_moves()` (menggabungkan
move 'order'+'gratis' produk yang sama di PICK/CO/LOAD) dan
`_action_done()`/`_reallocate_gratis_final_demand()`/`_reallocate_gratis_final_pair()`
(memecah ulang demand dua move Final berdasarkan qty aktual yang sampai).
Lihat plan 'groovy-hatching-pelican'.

PICK company ini `uu_only=True` (hanya ambil quant ber-pallet) dan CO
`book_full_pallet=True`, jadi barang uji dibungkus pallet (package) seperti
kondisi nyata -- meniru helper `wms_inherit_stock_barcode/tests/
test_outbound_barcode.py`. Simulasi scan memakai pola
`picking.write({'move_line_ids': [(0, 0, {...})]})` yang sama seperti
`_barcode_create_line()` di `wms_base_warehouse/tests/test_stock_type_int_p2p.py`
dan `_scan()`/`_scan_new_line_vals()` di `test_outbound_barcode.py` -- BUKAN
lewat HTTP/JSON-RPC.

Jalankan:
    python odoo-bin -c wms.conf -d DB_WMS_DEV_008 --test-enable --stop-after-init \\
        --test-tags /wms_base_warehouse:TestGratisOrderMergeSplit
"""
import math

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'wms_gratis')
class TestGratisOrderMergeSplit(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = cls.env['res.company'].search([('name', 'like', '1601')], limit=1)
        if not cls.company:
            msg = "Company 1601 (company_id=2) tidak ditemukan di database ini."
            raise ValueError(msg)

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
        # Ada dua 'LC-FINAL' (Affiliated/Unaffiliated) -- pakai channel Loco
        # 909 (Unaffiliated), dibedakan lewat move_type_sap.
        cls.type_final = PickingType.search([
            ('company_id', '=', cls.company.id),
            ('sequence_code', '=', 'LC-FINAL'),
            ('move_type_sap', '=', '909'),
        ], limit=1)
        cls.type_gi = PickingType.search([
            ('company_id', '=', cls.company.id),
            ('sequence_code', '=', 'GI-LOCO'),
        ], limit=1)
        for name, ptype in (
            ('PICK', cls.type_pick), ('CO', cls.type_co),
            ('LOAD', cls.type_load), ('LC-FINAL(909)', cls.type_final),
            ('GI-LOCO', cls.type_gi),
        ):
            if not ptype:
                raise ValueError("Operation type %s untuk company %s tidak ditemukan." % (name, cls.company.name))

        cls.loc_stock = cls.type_pick.default_location_src_id
        cls.loc_stg_out = cls.type_pick.default_location_dest_id

        # Route asli yang dipakai channel Loco 909 -- `shipping_selectable`,
        # bukan dibuat manual, supaya `action_confirm()` benar-benar memicu
        # kaskade MTO nyata (PICK make_to_stock -> CO/LOAD/LC-FINAL/GI-LOCO
        # make_to_order) lewat `stock.rule._run_pull()`.
        cls.route = cls.env['stock.route'].search([
            ('company_id', '=', cls.company.id),
            ('name', 'like', 'SO Loco 909'),
        ], limit=1)
        if not cls.route:
            msg = "Route '1601 - SO Loco 909' tidak ditemukan."
            raise ValueError(msg)

        reference = cls.env['product.product'].search([
            ('uom_bag_id', '!=', False),
            ('uom_pallet_id', '!=', False),
            ('tracking', '=', 'lot'),
        ], limit=1)
        if not reference:
            msg = "Tidak ada produk dengan UoM Bag & Pallet untuk dijadikan acuan."
            raise ValueError(msg)

        cls.product = cls.env['product.product'].create({
            'name': 'UT Gratis Merge Split',
            'default_code': 'UT-GRATIS-MRG',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'lot',
            'uom_id': reference.uom_id.id,
            'uom_bag_id': reference.uom_bag_id.id,
            'uom_pallet_id': reference.uom_pallet_id.id,
            'route_ids': [(6, 0, cls.route.ids)],
        })
        cls.product_plain = cls.env['product.product'].create({
            'name': 'UT Gratis Merge Split - Order Only',
            'default_code': 'UT-GRATIS-ORD',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'lot',
            'uom_id': reference.uom_id.id,
            'uom_bag_id': reference.uom_bag_id.id,
            'uom_pallet_id': reference.uom_pallet_id.id,
            'route_ids': [(6, 0, cls.route.ids)],
        })

        cls.partner = cls.env['res.partner'].create({
            'name': 'UT Gratis Customer',
        })

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _make_pallet(self, product, name, qty, lot=None):
        package = self.env['stock.package'].create({
            'name': name,
            'company_id': self.company.id,
        })
        package.yellow_tag = 'ready'
        lot = lot or self.env['stock.lot'].create({
            'name': name + '-LOT',
            'product_id': product.id,
            'company_id': self.company.id,
        })
        self.env['stock.quant']._update_available_quantity(
            product, self.loc_stock, qty, lot_id=lot, package_id=package,
        )
        quant = self.env['stock.quant'].sudo().search([
            ('product_id', '=', product.id),
            ('location_id', '=', self.loc_stock.id),
            ('lot_id', '=', lot.id),
            ('package_id', '=', package.id),
        ], limit=1)
        quant.write({'stock_type': 'UU'})
        return package, lot

    def _make_sale_order(self, product, lines):
        """`lines`: list of dict(qty, order_selection='order'/'gratis', rumus_gratis=int)."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'company_id': self.company.id,
            'warehouse_id': self.warehouse_id().id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': line['qty'],
                'order_selection': line.get('order_selection', 'order'),
                'rumus_gratis': line.get('rumus_gratis', 0),
            }) for line in lines],
        })
        order.action_confirm()
        return order

    def warehouse_id(self):
        if not hasattr(self, '_warehouse'):
            self._warehouse = self.env['stock.warehouse'].search(
                [('company_id', '=', self.company.id)], limit=1)
        return self._warehouse

    def _moves_at(self, order, picking_type):
        return order.order_line.move_ids.filtered(
            lambda m: m.picking_type_id == picking_type and m.state != 'cancel',
        )

    def _scan_line_vals(self, picking, product, qty, location, package, lot):
        """Tiruan `_createCommandVals()` (client Barcode): tanpa `stock_type`."""
        return {
            'picking_id': picking.id,
            'product_id': product.id,
            'product_uom_id': product.uom_id.id,
            'location_id': location.id,
            'location_dest_id': picking.location_dest_id.id,
            'lot_id': lot.id,
            'package_id': package.id,
            'result_package_id': package.id,
            'owner_id': False,
            'quantity': qty,
            'picked': True,
            'state': 'assigned',
        }

    def _scan(self, picking, commands):
        picking.write({'move_line_ids': commands})

    def _fill_bag_qty(self, picking, qty):
        """CO dan LOAD company ini `checker_out=True`, jadi wajib mengisi
        `bag_qty` sebelum validate. `bag_qty` HARUS bilangan bulat
        (`_validate_bag_qty()`) dan menulisnya memicu
        `_sync_qty_from_bag()` yang menurunkan ulang `quantity` dari
        `bag_qty * (uom_bag.factor / 1000)` -- angka itu tidak akan pas
        dengan `qty` uji manapun kecuali kebetulan kelipatan faktornya.
        Jadi bag_qty ditulis TERPISAH (nilai berapa pun, sekadar memenuhi
        syarat "sudah diisi") lalu `quantity` ditulis ulang di write()
        KEDUA supaya tidak ikut kena `_sync_qty_from_bag()` lagi (`vals`
        write kedua tidak mengandung `bag_qty`)."""
        picking.move_line_ids.write({'bag_qty': 1})
        picking.move_line_ids.write({'quantity': qty, 'picked': True})

    def _run_pick_co_load(self, order, product, pkg, lot, total_qty, load_qty):
        """Jalankan PICK (scan+validate penuh) -> CO (scan+validate penuh)
        -> LOAD (validate `load_qty` dari `total_qty`, sisanya backorder).
        Balikkan picking LOAD yang baru saja divalidasi."""
        pick = self._moves_at(order, self.type_pick).picking_id
        pick.action_assign()
        pick.move_line_ids.unlink()
        self._scan(pick, [(0, 0, self._scan_line_vals(
            pick, product, total_qty, self.loc_stock, pkg, lot,
        ))])
        self._validate(pick)

        co = self._moves_at(order, self.type_co).picking_id
        co.action_assign()
        self._write_co_scan_result(co, pkg, total_qty)
        self._validate(co)

        load = self._moves_at(order, self.type_load).picking_id
        load.action_assign()
        self._fill_bag_qty(load, load_qty)
        self._validate_partial(load)
        return load

    def _write_co_scan_result(self, co, package, qty):
        co.move_line_ids.write({'result_package_id': package.id})
        self._fill_bag_qty(co, qty)

    def _validate(self, picking):
        res = picking.button_validate()
        self.assertNotIsInstance(
            res, dict,
            "button_validate %s minta wizard tambahan: %s" % (picking.name, res),
        )
        return res

    def _validate_partial(self, picking):
        """Validasi parsial: operation type ini `create_backorder='always'`,
        jadi backorder dibuat OTOMATIS tanpa wizard (`button_validate()`
        langsung `True`) -- beda dengan Final yang `create_backorder='never'`.
        Tetap tangani kemungkinan wizard (`dict`) untuk jaga-jaga kalau
        konfigurasi operation type berubah jadi 'ask'.
        """
        res = picking.button_validate()
        if isinstance(res, dict):
            wizard = self.env[res['res_model']].with_context(**res['context']).create({})
            wizard.process()
        self.assertEqual(picking.state, 'done')
        return res

    # ==================================================================
    # 1. Order line tanpa gratis: perilaku normal, tidak ada reallocation
    # ==================================================================
    def test_01_order_only_no_gratis_normal_flow(self):
        pkg, _lot = self._make_pallet(self.product_plain, 'UT-GRTS-01', 100.0)

        order = self._make_sale_order(self.product_plain, [
            {'qty': 100.0, 'order_selection': 'order', 'rumus_gratis': 0},
        ])

        pick_moves = self._moves_at(order, self.type_pick)
        self.assertEqual(len(pick_moves), 1, "Harus ada satu move PICK untuk line tanpa gratis.")
        self.assertEqual(pick_moves.product_uom_qty, 100.0)

        final_moves = self._moves_at(order, self.type_final)
        self.assertEqual(len(final_moves), 1, "Tanpa gratis, Final tetap harus satu move.")
        self.assertEqual(final_moves.order_selection, 'order')
        self.assertEqual(final_moves.product_uom_qty, 100.0)

        pick = pick_moves.picking_id
        pick.action_assign()
        self.assertEqual(pick.state, 'assigned')
        pick.move_line_ids.write({'result_package_id': pkg.id})
        self._validate(pick)
        self.assertEqual(pick.state, 'done')

        # Reallocation dipanggil (lewat _action_done -> _reallocate_gratis_final_demand)
        # tapi harus no-op: hanya ada satu move Final (order_selection == 'order'
        # saja), _reallocate_gratis_final_pair() mensyaratkan PERSIS 2 move
        # dengan order_selection {'order','gratis'} sebelum menulis apa pun.
        final_moves = self._moves_at(order, self.type_final)
        self.assertEqual(len(final_moves), 1)
        self.assertEqual(final_moves.product_uom_qty, 100.0,
                         "Demand Final berubah walau tidak ada pasangan gratis.")
        self.assertNotEqual(final_moves.state, 'cancel')

    # ==================================================================
    # 2. Order + gratis: HARUS MERGE jadi satu move di PICK (qty 105)
    # ==================================================================
    def test_02_order_plus_gratis_merges_at_pick(self):
        self._make_pallet(self.product, 'UT-GRTS-02', 200.0)

        order = self._make_sale_order(self.product, [
            {'qty': 100.0, 'order_selection': 'order', 'rumus_gratis': 26},
            {'qty': 5.0, 'order_selection': 'gratis', 'rumus_gratis': 26},
        ])

        pick_moves = self._moves_at(order, self.type_pick)
        self.assertEqual(
            len(pick_moves), 1,
            "PICK harus punya SATU move untuk order+gratis produk yang sama "
            "(dapat %s move)." % len(pick_moves),
        )
        self.assertEqual(
            pick_moves.product_uom_qty, 105.0,
            "qty move PICK survivor harus 100 (order) + 5 (gratis) = 105.",
        )
        self.assertEqual(pick_moves.order_selection, 'order',
                         "Survivor merge harus baris 'order' yang menang.")

        co_moves = self._moves_at(order, self.type_co)
        self.assertEqual(len(co_moves), 1, "CO juga harus tetap satu move gabungan.")
        self.assertEqual(co_moves.product_uom_qty, 105.0)

        load_moves = self._moves_at(order, self.type_load)
        self.assertEqual(len(load_moves), 1, "LOAD juga harus tetap satu move gabungan.")
        self.assertEqual(load_moves.product_uom_qty, 105.0)

        # Final SENGAJA dikecualikan dari merge -- tetap dua move terpisah.
        final_moves = self._moves_at(order, self.type_final)
        self.assertEqual(
            len(final_moves), 2,
            "Final harus tetap dua move terpisah (order & gratis), TIDAK di-merge.",
        )
        self.assertEqual(set(final_moves.mapped('order_selection')), {'order', 'gratis'})

    # ==================================================================
    # 2b. Regresi nyata (SO S00846): shortage PICK/CO (create_backorder=
    #     'always') tidak boleh disalahartikan sebagai "sibling gratis" oleh
    #     _merge_gratis_moves() -- kalau salah, backorder yang semestinya
    #     dibuat core malah dibatalkan diam-diam, dan demand move survivor
    #     yang sudah benar direduksi core ikut ditulis ulang jadi kembali ke
    #     total semula (qty duplikat).
    # ==================================================================
    def test_02b_pick_shortage_creates_real_backorder_not_fake_merge(self):
        pkg, lot = self._make_pallet(self.product, 'UT-GRTS-02B', 60.0)

        order = self._make_sale_order(self.product, [
            {'qty': 100.0, 'order_selection': 'order', 'rumus_gratis': 0},
            {'qty': 5.0, 'order_selection': 'gratis', 'rumus_gratis': 0},
        ])

        pick = self._moves_at(order, self.type_pick).picking_id
        pick.action_assign()
        pick_move = pick.move_ids
        self.assertEqual(len(pick_move), 1, "PICK harus tetap satu move gabungan sebelum validate.")
        self.assertEqual(pick_move.product_uom_qty, 105.0)

        pick.move_line_ids.unlink()
        self._scan(pick, [(0, 0, self._scan_line_vals(
            pick, self.product, 60.0, self.loc_stock, pkg, lot,
        ))])
        self._validate_partial(pick)

        self.assertEqual(
            pick_move.product_uom_qty, 60.0,
            "Demand move PICK yang sudah selesai HARUS tetap 60 (qty yang "
            "benar-benar di-scan) -- kalau kembali ke 105, berarti "
            "_merge_gratis_moves() salah mengira move backorder sisa "
            "sebagai sibling gratis dan menjumlahkan qty-nya balik.",
        )
        self.assertEqual(pick_move.state, 'done')

        backorder_picks = self.env['stock.picking'].search([('backorder_id', '=', pick.id)])
        self.assertEqual(
            len(backorder_picks), 1,
            "PICK ber-create_backorder='always' HARUS membentuk picking "
            "backorder untuk sisa 45 (105-60) -- kalau tidak ada sama "
            "sekali, move sisanya kemungkinan dibatalkan diam-diam oleh "
            "merge gratis, bukan diproses sebagai backorder oleh core.",
        )
        backorder_move = backorder_picks.move_ids
        self.assertNotEqual(
            backorder_move.state, 'cancel',
            "Move backorder tidak boleh ikut dibatalkan oleh merge gratis.",
        )
        self.assertEqual(backorder_move.product_uom_qty, 45.0)

        co_moves = self._moves_at(order, self.type_co)
        self.assertEqual(len(co_moves), 1, "CO tetap harus satu move (belum ada qty tambahan dari backorder).")
        self.assertEqual(
            co_moves.product_uom_qty, 105.0,
            "Demand CO belum boleh berubah -- backorder PICK belum diproses.",
        )

    # ==================================================================
    # 3 & 4. Rantai penuh lewat scan barcode, Load kurang dari demand ->
    #         Final: DEMAND (product_uom_qty) TETAP sesuai SO (100/5),
    #         yang di-reallocate cuma QUANTITY (aktual/reserved), displit
    #         qty_gratis=floor(100/26)=3, qty_order=97.
    # ==================================================================
    def test_03_04_full_chain_barcode_scan_load_shortage_splits_final(self):
        pkg, lot = self._make_pallet(self.product, 'UT-GRTS-034', 105.0)

        order = self._make_sale_order(self.product, [
            {'qty': 100.0, 'order_selection': 'order', 'rumus_gratis': 26},
            {'qty': 5.0, 'order_selection': 'gratis', 'rumus_gratis': 26},
        ])

        pick = self._moves_at(order, self.type_pick).picking_id
        pick.action_assign()
        self.assertEqual(pick.state, 'assigned')
        pick.move_line_ids.unlink()
        self._scan(pick, [(0, 0, self._scan_line_vals(
            pick, self.product, 105.0, self.loc_stock, pkg, lot,
        ))])
        self._validate(pick)
        self.assertEqual(pick.state, 'done')

        co_moves = self._moves_at(order, self.type_co)
        co = co_moves.picking_id
        co.action_assign()
        self.assertEqual(co.state, 'assigned')
        self._write_co_scan_result(co, pkg, 105.0)
        self._validate(co)
        self.assertEqual(co.state, 'done')

        load_moves = self._moves_at(order, self.type_load)
        load = load_moves.picking_id
        load.action_assign()
        self.assertEqual(load.state, 'assigned')
        self.assertEqual(load.move_line_ids.quantity, 105.0)

        # Skenario shortage: scan/validate cuma 100 dari 105 -- backorder utk sisanya.
        self._fill_bag_qty(load, 100.0)
        self._validate_partial(load)

        final_moves = self._moves_at(order, self.type_final)
        self.assertEqual(len(final_moves), 2, "Final tetap dua move terpisah.")
        order_final = final_moves.filtered(lambda m: m.order_selection == 'order')
        gratis_final = final_moves.filtered(lambda m: m.order_selection == 'gratis')
        self.assertEqual(len(order_final), 1)
        self.assertEqual(len(gratis_final), 1)

        # Demand Final HARUS tetap sesuai sale.order.line asli (100/5) --
        # tidak pernah ikut berkurang walau LOAD baru sebagian selesai.
        self.assertEqual(
            order_final.product_uom_qty, 100.0,
            "Demand Final order harus tetap sesuai SO (100), bukan hasil "
            "kumulatif LOAD.",
        )
        self.assertEqual(
            gratis_final.product_uom_qty, 5.0,
            "Demand Final gratis harus tetap sesuai SO (5), bukan hasil "
            "kumulatif LOAD.",
        )

        # QUANTITY (aktual/reserved) itulah yang dihitung kumulatif & displit.
        expected_gratis = math.floor(100.0 / 26)
        expected_order = 100.0 - expected_gratis
        self.assertEqual(
            gratis_final.quantity, expected_gratis,
            "qty_gratis (quantity) harus floor(100/26)=%s." % expected_gratis,
        )
        self.assertEqual(
            order_final.quantity, expected_order,
            "qty_order (quantity) harus 100 - qty_gratis = %s." % expected_order,
        )
        self.assertNotEqual(gratis_final.state, 'cancel')

        # Regresi nyata (SO S00937): menulis `quantity` (bukan demand) lewat
        # inverse core `_set_quantity()` sudah otomatis membentuk
        # move_line_ids dan meng-update state -- TIDAK perlu
        # `_action_assign()`/"Check Availability" manual lagi.
        self.assertEqual(
            order_final.state, 'partially_available',
            "Final order harus otomatis ter-reserve sebagian (quantity < "
            "demand asli) tanpa perlu Check Availability manual.",
        )
        self.assertEqual(
            gratis_final.state, 'partially_available',
            "Final gratis harus otomatis ter-reserve sebagian tanpa perlu "
            "Check Availability manual.",
        )

    # ==================================================================
    # 5. Qty aktual < rumus_gratis: qty_gratis jadi 0 -- demand dikosongkan,
    #    TAPI move gratis Final TIDAK BOLEH dibatalkan (regresi nyata SO
    #    S00865: move gratis yang dibatalkan hilang dari `move_dest_ids`
    #    setiap backorder split berikutnya -- lihat
    #    `stock/models/stock_move.py::_prepare_move_split_vals` core --
    #    sehingga pasangan order/gratis di Final tidak pernah lengkap lagi
    #    dan demand order BEKU di leg pertama walau LOAD susulan selesai).
    #    Test ini lanjut ke LOAD leg KEDUA untuk membuktikan demand Final
    #    tetap ikut ter-update kumulatif, bukan macet.
    # ==================================================================
    def test_05_actual_qty_below_rumus_gratis_then_second_load_leg_still_recalculates(self):
        pkg, lot = self._make_pallet(self.product, 'UT-GRTS-05', 105.0)

        order = self._make_sale_order(self.product, [
            {'qty': 100.0, 'order_selection': 'order', 'rumus_gratis': 26},
            {'qty': 5.0, 'order_selection': 'gratis', 'rumus_gratis': 26},
        ])

        pick = self._moves_at(order, self.type_pick).picking_id
        pick.action_assign()
        pick.move_line_ids.unlink()
        self._scan(pick, [(0, 0, self._scan_line_vals(
            pick, self.product, 105.0, self.loc_stock, pkg, lot,
        ))])
        self._validate(pick)

        co = self._moves_at(order, self.type_co).picking_id
        co.action_assign()
        self._write_co_scan_result(co, pkg, 105.0)
        self._validate(co)

        def gratis_final():
            return order.order_line.move_ids.filtered(
                lambda m: m.picking_type_id == self.type_final and m.order_selection == 'gratis',
            )

        # Leg 1: hanya 10 dari 105 yang benar-benar dimuat -- di bawah
        # rumus_gratis (26), jadi qty_gratis = 0.
        load = self._moves_at(order, self.type_load).picking_id
        load.action_assign()
        self._fill_bag_qty(load, 10.0)
        self._validate_partial(load)

        order_final = self._moves_at(order, self.type_final).filtered(lambda m: m.order_selection == 'order')
        self.assertEqual(order_final.product_uom_qty, 100.0,
                         "Demand Final order harus tetap sesuai SO (100).")
        self.assertEqual(gratis_final().product_uom_qty, 5.0,
                         "Demand Final gratis harus tetap sesuai SO (5).")
        self.assertEqual(order_final.quantity, 10.0,
                         "qty_order (quantity) harus sama dengan qty_actual (10) karena qty_gratis=0.")
        self.assertEqual(gratis_final().quantity, 0.0)
        self.assertNotIn(
            gratis_final().state, ('done', 'cancel'),
            "Move gratis Final TIDAK BOLEH dibatalkan hanya karena qty_gratis "
            "sementara 0 -- kalau dibatalkan, ia hilang dari move_dest_ids "
            "backorder LOAD berikutnya (core _prepare_move_split_vals) dan "
            "demand Final macet selamanya (regresi S00865).",
        )

        # Leg 2: backorder LOAD dari sisa 95 mengirim 16 lagi -- kumulatif 26,
        # persis 1x rumus_gratis -- floor(26/26)=1, qty_order=25.
        load2 = self._moves_at(order, self.type_load).picking_id - load
        load2.action_assign()
        self._fill_bag_qty(load2, 16.0)
        self._validate_partial(load2)

        order_final = self._moves_at(order, self.type_final).filtered(lambda m: m.order_selection == 'order')
        self.assertEqual(
            order_final.product_uom_qty, 100.0,
            "Demand Final order harus TETAP 100 (SO asli) -- tidak pernah "
            "berubah walau LOAD baru sebagian selesai.",
        )
        self.assertEqual(gratis_final().product_uom_qty, 5.0)
        self.assertEqual(
            order_final.quantity, 25.0,
            "Quantity Final harus ikut naik ke kumulatif (10+16=26, "
            "floor(26/26)=1 gratis, order=25) -- kalau masih 10, berarti "
            "kumulatifnya macet di leg pertama seperti bug S00865.",
        )
        self.assertEqual(gratis_final().quantity, 1.0)

    # ==================================================================
    # 6. Positif: reallocation harus MERAMBAT ke Good Issue (GI-LOCO), bukan
    #    berhenti di Final -- regresi nyata SO S00865 (demand GI beku di
    #    angka SO-line asli walau Final sudah displit benar, karena GI dibuat
    #    terpisah dari Final sejak awal dan tidak ikut ter-reallocate kalau
    #    hanya dest_moves langsung dari move sumber yang dicek).
    # ==================================================================
    def test_06_reallocation_cascades_past_final_to_gi(self):
        pkg, lot = self._make_pallet(self.product, 'UT-GRTS-06', 105.0)

        order = self._make_sale_order(self.product, [
            {'qty': 100.0, 'order_selection': 'order', 'rumus_gratis': 21},
            {'qty': 5.0, 'order_selection': 'gratis', 'rumus_gratis': 21},
        ])
        self._run_pick_co_load(order, self.product, pkg, lot, 105.0, 84.0)

        final_moves = self._moves_at(order, self.type_final)
        order_final = final_moves.filtered(lambda m: m.order_selection == 'order')
        gratis_final = final_moves.filtered(lambda m: m.order_selection == 'gratis')
        self.assertEqual(order_final.quantity, 80.0, "Final order: floor(84/21)=4 gratis, sisanya 80 order.")
        self.assertEqual(gratis_final.quantity, 4.0)

        # LC-FINAL company ini `create_backorder='never'` -- validate dengan
        # quantity < demand langsung menutup picking, sisa diforfeit (bukan
        # backorder baru), persis skenario nyata S00865/S00937.
        final_picking = final_moves.picking_id
        for m in final_moves:
            m.move_line_ids.write({'picked': True})
        self._validate(final_picking)
        self.assertEqual(final_picking.state, 'done')

        gi_moves = self._moves_at(order, self.type_gi)
        gi_order = gi_moves.filtered(lambda m: m.order_selection == 'order')
        gi_gratis = gi_moves.filtered(lambda m: m.order_selection == 'gratis')
        self.assertEqual(len(gi_moves), 2, "GI harus tetap dua move terpisah (order & gratis).")
        self.assertEqual(
            gi_order.product_uom_qty, 100.0,
            "Demand GI harus tetap sesuai SO (100), sama seperti Final.",
        )
        self.assertEqual(gi_gratis.product_uom_qty, 5.0)
        self.assertEqual(
            gi_order.quantity, 80.0,
            "Quantity GI harus IKUT ter-reallocate dari qty yang benar-benar "
            "selesai di Final (80/4) -- kalau masih 100/5 (demand SO asli) "
            "atau 0, berarti reallocation berhenti di Final dan tidak "
            "merambat ke GI (regresi S00865).",
        )
        self.assertEqual(gi_gratis.quantity, 4.0)
        self.assertNotIn(gi_gratis.state, ('done', 'cancel'))

    # ==================================================================
    # 7. Positif/edge: lebih dari satu line 'gratis' untuk order+produk yang
    #    sama -- semua digabung ke satu survivor 'order', bukan crash.
    # ==================================================================
    def test_07_multiple_gratis_lines_fold_into_one_survivor(self):
        pkg, lot = self._make_pallet(self.product, 'UT-GRTS-07', 105.0)

        order = self._make_sale_order(self.product, [
            {'qty': 100.0, 'order_selection': 'order', 'rumus_gratis': 21},
            {'qty': 3.0, 'order_selection': 'gratis', 'rumus_gratis': 21},
            {'qty': 2.0, 'order_selection': 'gratis', 'rumus_gratis': 21},
        ])

        pick_moves = self._moves_at(order, self.type_pick)
        self.assertEqual(
            len(pick_moves), 1,
            "Ketiga line (1 order + 2 gratis) harus tetap melebur jadi SATU "
            "move survivor, bukan crash atau tersisa 2+ move.",
        )
        self.assertEqual(pick_moves.product_uom_qty, 105.0, "100 + 3 + 2 = 105.")
        self.assertEqual(pick_moves.order_selection, 'order')

        # Final SENGAJA TIDAK PERNAH digabung (dikecualikan dari merge sejak
        # awal), jadi tetap ada 3 move -- satu per SO line asli (1 order +
        # 2 gratis). `_reallocate_gratis_final_pair()` mensyaratkan PERSIS 2
        # move untuk bisa memasangkan order/gratis, jadi utk kasus 3-line
        # yang di luar model bisnis normal ini, reallocation di Final
        # otomatis no-op (sesuai warning yang sudah dicatat saat merge) --
        # bukan bug, cuma di luar cakupan fitur split.
        final_moves = self._moves_at(order, self.type_final)
        self.assertEqual(
            len(final_moves), 3,
            "Final tidak pernah di-merge -- harus tetap 3 move (1 order + "
            "2 gratis), masing-masing mewarisi SO line asalnya.",
        )
        self.assertEqual(
            len(final_moves.filtered(lambda m: m.order_selection == 'gratis')), 2,
        )
        self.assertEqual(set(final_moves.mapped('order_selection')), {'order', 'gratis'})

    # ==================================================================
    # 8. Negatif: dua sale.order berbeda untuk produk yang sama TIDAK BOLEH
    #    saling melebur -- domain `_merge_gratis_moves()` mengunci per
    #    `sale_line_id.order_id`, ini membuktikan itu benar-benar terjaga.
    # ==================================================================
    def test_08_two_different_orders_never_merge_across_each_other(self):
        pkg_a, lot_a = self._make_pallet(self.product, 'UT-GRTS-08-A', 105.0)
        pkg_b, lot_b = self._make_pallet(self.product, 'UT-GRTS-08-B', 210.0)

        order_a = self._make_sale_order(self.product, [
            {'qty': 100.0, 'order_selection': 'order', 'rumus_gratis': 21},
            {'qty': 5.0, 'order_selection': 'gratis', 'rumus_gratis': 21},
        ])
        order_b = self._make_sale_order(self.product, [
            {'qty': 200.0, 'order_selection': 'order', 'rumus_gratis': 21},
            {'qty': 10.0, 'order_selection': 'gratis', 'rumus_gratis': 21},
        ])

        pick_a = self._moves_at(order_a, self.type_pick)
        pick_b = self._moves_at(order_b, self.type_pick)
        self.assertEqual(len(pick_a), 1)
        self.assertEqual(len(pick_b), 1)
        self.assertNotEqual(
            pick_a.picking_id, pick_b.picking_id,
            "Dua order beda harus tetap punya picking PICK sendiri-sendiri.",
        )
        self.assertEqual(
            pick_a.product_uom_qty, 105.0,
            "Demand PICK order_a tidak boleh ikut kebawa qty order_b (105+210).",
        )
        self.assertEqual(pick_b.product_uom_qty, 210.0)

    # ==================================================================
    # 9. Positif/edge: LOAD terkirim PENUH (tanpa shortage sama sekali) --
    #    hasil split kumulatif harus persis balik ke proporsi order/gratis
    #    SO aslinya (100/5), bukan angka lain. `restrict_over_demand=True`
    #    pada LOAD company ini juga membuktikan alur normal (qty pas demand)
    #    tidak pernah menyentuh guard itu.
    # ==================================================================
    def test_09_full_delivery_no_shortage_matches_original_so_split(self):
        pkg, lot = self._make_pallet(self.product, 'UT-GRTS-09', 105.0)

        order = self._make_sale_order(self.product, [
            {'qty': 100.0, 'order_selection': 'order', 'rumus_gratis': 21},
            {'qty': 5.0, 'order_selection': 'gratis', 'rumus_gratis': 21},
        ])
        load = self._run_pick_co_load(order, self.product, pkg, lot, 105.0, 105.0)
        self.assertEqual(load.state, 'done')

        final_moves = self._moves_at(order, self.type_final)
        order_final = final_moves.filtered(lambda m: m.order_selection == 'order')
        gratis_final = final_moves.filtered(lambda m: m.order_selection == 'gratis')

        # floor(105/21)=5 gratis, order=100 -- persis proporsi SO aslinya.
        self.assertEqual(gratis_final.quantity, 5.0)
        self.assertEqual(order_final.quantity, 100.0)
        self.assertEqual(order_final.product_uom_qty, 100.0)
        self.assertEqual(gratis_final.product_uom_qty, 5.0)
        self.assertEqual(order_final.state, 'assigned', "Qty penuh -> assigned, bukan partially_available.")
        self.assertEqual(gratis_final.state, 'assigned')

    # ==================================================================
    # 10. Regresi nyata SO S00980: order line pakai UoM 'BAG 20' (1 BAG =
    #     20 kg) sementara stock.move selalu dalam UoM stok produk (kg).
    #     `rumus_gratis` dimasukkan dalam satuan BAG (21 = "1 gratis tiap
    #     21 BAG"), jadi floor-division WAJIB dihitung dalam BAG, bukan kg
    #     mentah -- kalau tidak, hasilnya pecahan salah unit (gratis "4.55"
    #     alih-alih "4", persis yang dilaporkan pada S00980).
    # ==================================================================
    def test_10_rumus_gratis_uom_mismatch_uses_order_line_uom_not_move_uom(self):
        bag_uom = self.env['uom.uom'].search([('name', '=', 'BAG 20')], limit=1)
        if not bag_uom:
            self.skipTest("UoM 'BAG 20' tidak ditemukan di database ini.")

        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'company_id': self.company.id,
            'warehouse_id': self.warehouse_id().id,
            'order_line': [
                (0, 0, {
                    'product_id': self.product.id, 'product_uom_qty': 100.0,
                    'product_uom_id': bag_uom.id, 'order_selection': 'order', 'rumus_gratis': 21,
                }),
                (0, 0, {
                    'product_id': self.product.id, 'product_uom_qty': 4.0,
                    'product_uom_id': bag_uom.id, 'order_selection': 'gratis', 'rumus_gratis': 21,
                }),
            ],
        })
        order.action_confirm()

        final_moves = self._moves_at(order, self.type_final)
        order_final = final_moves.filtered(lambda m: m.order_selection == 'order')
        gratis_final = final_moves.filtered(lambda m: m.order_selection == 'gratis')
        self.assertEqual(order_final.product_uom_qty, 2000.0, "100 BAG x 20 = 2000 kg.")
        self.assertEqual(gratis_final.product_uom_qty, 80.0, "4 BAG x 20 = 80 kg.")

        # Simulasikan LOAD yang sudah kumulatif mengirim 1920 kg (= 96 BAG)
        # -- persis angka nyata SO S00980 -- tanpa menjalankan scan
        # PICK/CO/LOAD penuh; method yang diuji cuma peduli pada
        # `move_orig_ids` yang `state == 'done'` dan `quantity`-nya.
        load_moves = self._moves_at(order, self.type_load)
        load_moves.sudo().write({'quantity': 1920.0, 'state': 'done'})

        order_final._reallocate_gratis_final_pair(order_final | gratis_final)

        # 1920 kg = 96 BAG. floor(96/21)=4 gratis BAG (=80kg), sisanya 92
        # BAG (=1840kg) order -- BUKAN floor(1920kg/21)=91 (salah unit,
        # bug S00980).
        self.assertEqual(
            gratis_final.quantity, 80.0,
            "qty_gratis harus 4 BAG (=80kg) -- floor dihitung dalam BAG "
            "(96/21=4), bukan floor(1920kg/21)=91 yang salah unit.",
        )
        self.assertEqual(order_final.quantity, 1840.0, "92 BAG x 20 = 1840 kg.")

    # ==================================================================
    # 11. Kebalikan dari test 10: sale.order.line pakai UoM yang SAMA
    #     dengan UoM move (kg langsung, bukan BAG) -- konversi jadi no-op
    #     (`order_uom == move_uom`), jadi hasilnya harus identik dengan
    #     floor-division polos seperti sebelum perbaikan UOM. Ini
    #     memastikan perbaikan test 10 tidak mengubah/merusak kasus yang
    #     sudah benar sebelumnya (order line kg, produk kg, tanpa BAG).
    # ==================================================================
    def test_11_rumus_gratis_same_uom_as_move_no_conversion_needed(self):
        kg_uom = self.product.uom_id
        self.assertEqual(kg_uom.name, 'kg', "Prasyarat: UoM dasar produk uji ini adalah kg.")

        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'company_id': self.company.id,
            'warehouse_id': self.warehouse_id().id,
            'order_line': [
                (0, 0, {
                    'product_id': self.product.id, 'product_uom_qty': 2000.0,
                    'product_uom_id': kg_uom.id, 'order_selection': 'order', 'rumus_gratis': 21,
                }),
                (0, 0, {
                    'product_id': self.product.id, 'product_uom_qty': 80.0,
                    'product_uom_id': kg_uom.id, 'order_selection': 'gratis', 'rumus_gratis': 21,
                }),
            ],
        })
        order.action_confirm()

        final_moves = self._moves_at(order, self.type_final)
        order_final = final_moves.filtered(lambda m: m.order_selection == 'order')
        gratis_final = final_moves.filtered(lambda m: m.order_selection == 'gratis')
        # Order line & move sama-sama kg -- demand move langsung sama
        # dengan qty SO line, tidak ada faktor konversi (2000/80, bukan
        # 100/4 seperti test 10 yang pakai BAG).
        self.assertEqual(order_final.product_uom_qty, 2000.0)
        self.assertEqual(gratis_final.product_uom_qty, 80.0)

        # Angka kumulatif LOAD yang SAMA PERSIS dengan test 10 (1920 kg),
        # tapi sekarang rumus_gratis (21) dan qty_actual sama-sama dalam
        # kg -- tanpa konversi apa pun, floor(1920/21)=91.
        load_moves = self._moves_at(order, self.type_load)
        load_moves.sudo().write({'quantity': 1920.0, 'state': 'done'})

        order_final._reallocate_gratis_final_pair(order_final | gratis_final)

        self.assertEqual(
            gratis_final.quantity, 91.0,
            "Tanpa mismatch UoM, floor(1920/21)=91 kg -- BEDA dengan hasil "
            "test 10 (80 kg) justru karena di sini rumus_gratis memang "
            "dalam kg, bukan BAG. Membuktikan konversi UOM hanya aktif "
            "kalau order_uom != move_uom, tidak mengubah kasus yang sudah "
            "benar.",
        )
        self.assertEqual(order_final.quantity, 1829.0)

    def test_12_reallocation_repairs_lotless_fallback_reservation(self):
        location = self.type_final.default_location_src_id
        destination = self.type_final.default_location_dest_id
        lot = self.env['stock.lot'].create({
            'name': 'UT-GRATIS-LOTLESS-LOT',
            'product_id': self.product.id,
            'company_id': self.company.id,
        })
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.type_final.id,
            'location_id': location.id,
            'location_dest_id': destination.id,
            'company_id': self.company.id,
        })
        move = self.env['stock.move'].create({
            'picking_id': picking.id,
            'product_id': self.product.id,
            'product_uom_qty': 20.0,
            'product_uom': self.product.uom_id.id,
            'order_selection': 'order',
            'location_id': location.id,
            'location_dest_id': destination.id,
            'company_id': self.company.id,
        })
        gratis_move = self.env['stock.move'].create({
            'picking_id': picking.id,
            'product_id': self.product.id,
            'product_uom_qty': 1.0,
            'product_uom': self.product.uom_id.id,
            'order_selection': 'gratis',
            'location_id': location.id,
            'location_dest_id': destination.id,
            'company_id': self.company.id,
        })
        (move | gratis_move)._action_confirm(merge=False)
        fallback = self.env['stock.move.line'].create({
            'move_id': move.id,
            'picking_id': picking.id,
            'product_id': self.product.id,
            'product_uom_id': self.product.uom_id.id,
            'quantity': 20.0,
            'location_id': location.id,
            'location_dest_id': destination.id,
            'company_id': self.company.id,
        })
        self.assertFalse(fallback.lot_id)
        self.env['stock.quant']._update_available_quantity(
            self.product, location, 20.0, lot_id=lot,
        )

        fallback.write({'picked': True})
        picking.with_context(test_stock_no_negative=True).button_validate()

        self.assertFalse(fallback.exists())
        self.assertEqual(picking.state, 'done')
        self.assertEqual(move.move_line_ids.lot_id, lot)
        self.assertEqual(move.move_line_ids.quantity, 20.0)

    def test_13_repair_ignores_regular_outbound_move(self):
        location = self.type_final.default_location_src_id
        destination = self.type_final.default_location_dest_id
        lot = self.env['stock.lot'].create({
            'name': 'UT-REGULAR-LOTLESS-LOT',
            'product_id': self.product.id,
            'company_id': self.company.id,
        })
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.type_final.id,
            'location_id': location.id,
            'location_dest_id': destination.id,
            'company_id': self.company.id,
        })
        move = self.env['stock.move'].create({
            'picking_id': picking.id,
            'product_id': self.product.id,
            'product_uom_qty': 20.0,
            'product_uom': self.product.uom_id.id,
            'location_id': location.id,
            'location_dest_id': destination.id,
            'company_id': self.company.id,
        })
        move._action_confirm()
        fallback = self.env['stock.move.line'].create({
            'move_id': move.id,
            'picking_id': picking.id,
            'product_id': self.product.id,
            'product_uom_id': self.product.uom_id.id,
            'quantity': 20.0,
            'location_id': location.id,
            'location_dest_id': destination.id,
            'company_id': self.company.id,
            'picked': True,
        })
        self.env['stock.quant']._update_available_quantity(
            self.product, location, 20.0, lot_id=lot,
        )

        with self.assertRaises(UserError):
            picking.button_validate()

        self.assertTrue(fallback.exists())
        self.assertFalse(fallback.lot_id)
