"""Nama lot GR produksi hanya boleh lahir dari `_get_or_create_lot()`.

Keluhannya: sejak beberapa hari terakhir muncul lot bernama `160110003526|71`,
`148110003725|12`, dst. -- padahal format resminya berasal dari
`production.code` (mis. `31965731 - 17022028`).

Asal-usulnya:

1. QR label PO SAP berisi payload `f"{po_number}|{production_line.code}"`
   (`wms_production_order_sap/wizards/qr_po_sap.py::_get_qr_image_base64`).
   QR itu untuk layar scanner GR FG, bukan untuk layar Barcode.
2. Kalau QR itu di-scan di layar Barcode, core tidak mengenalinya sebagai
   produk/lokasi/pallet, lalu jatuh ke blok "we assume it's a new lot/serial
   number" (`stock_barcode/static/src/models/barcode_model.js`) dan mengisi
   `stock.move.line.lot_name` dengan payload mentah tadi.
3. Picking GR produksi ber-`use_create_lots=True`, jadi
   `stock/models/stock_move_line.py::_action_done` membuat `stock.lot` dari
   `lot_name` itu -- tapi hanya kalau `lot_id` masih kosong, yaitu ketika
   `production_line_id` belum sempat terisi saat baris dibuat.

Test di bawah mengunci ketiga lapis pengamannya: `create()`, `write()`, dan
`_action_done()`.

Jalankan (tag custom, bukan `/wms_base_warehouse` -- `@tagged` di sini menghapus
tag `standard` sehingga bentuk `/<module>` menghasilkan 0 test):

    D:\\CPP\\Odoo19-ENT\\python\\python.exe odoo-bin -c wms.conf \\
        -u wms_base_warehouse --test-enable --test-tags wms_gr_lot \\
        --stop-after-init --no-http
"""

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

# Payload QR PO SAP yang tidak sengaja di-scan operator.
SCANNED_QR = '160110003526|71'


@tagged('post_install', '-at_install', 'wms_gr_lot')
class TestGrProdLotName(TransactionCase):

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
        cls.prod_in_move_type = icp.get_param('prod_in_move_type')
        if not cls.prod_in_move_type:
            cls.prod_in_move_type = '101'
            icp.set_param('prod_in_move_type', cls.prod_in_move_type)
        icp.set_param('upload_stock', 'false')

        # Sumber GR produksi di lapangan adalah lokasi virtual `Production`,
        # bukan supplier -- dan justru quant "jurnal lawan" di sanalah yang
        # dulu mencemari `production_line_id` baris baru.
        cls.production_loc = cls.env['stock.location'].create({
            'name': 'GRLOT-PRODUCTION',
            'usage': 'production',
            'company_id': cls.company.id,
        })
        cls.bin_dest = cls.env['stock.location'].create({
            'name': 'GRLOT-BIN',
            'location_id': cls.warehouse.lot_stock_id.id,
            'usage': 'internal',
            'company_id': cls.company.id,
        })

        cls.product = cls.env['product.product'].create({
            'name': 'GRLOT Product',
            'default_code': 'GRLOT-01',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'lot',
        })
        # Varian dengan masa simpan: hook `write()` baru menghasilkan lot kalau
        # `production_line_id` DAN `expiration_date` sama-sama terisi.
        cls.product_exp = cls.env['product.product'].create({
            'name': 'GRLOT Product Exp',
            'default_code': 'GRLOT-02',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'lot',
            'use_expiration_date': True,
            'expiration_time': 180,
            'use_time': 150,
            'removal_time': 120,
            'alert_time': 90,
        })

        cls.production_line = cls.env['production.line'].create({
            'name': 'GRLOT Line 1',
            'code': 'GRL1',
            'prod_code': 'P1',
            'company_id': cls.company.id,
        })
        cls.production_line_2 = cls.env['production.line'].create({
            'name': 'GRLOT Line 2',
            'code': 'GRL2',
            'prod_code': 'P9',
            'company_id': cls.company.id,
        })

        # Format lot sengaja dibuat sederhana dan TIDAK memakai
        # `moveline.expiration_date`: produk uji tidak memakai masa simpan,
        # dan justru kombinasi itulah yang membuka lubangnya (lihat
        # `test_validate_generates_lot_even_when_write_hook_skipped`).
        cls.production_code = cls.env['production.code'].sudo().search(
            [('company_id', '=', cls.company.id)], limit=1
        )
        lot_format = 'UT-GR-{moveline.production_line_id.prod_code}'
        if cls.production_code:
            cls.production_code.write({'code': lot_format})
        else:
            cls.production_code = cls.env['production.code'].sudo().create({
                'company_id': cls.company.id,
                'code': lot_format,
            })
        cls.expected_lot_name = 'UT-GR-P1'

        cls.type_gr = cls.env['stock.picking.type'].create({
            'name': 'GRLOT Inbound FG Production',
            'sequence_code': 'GRLOT',
            'code': 'incoming',
            'warehouse_id': cls.warehouse.id,
            'company_id': cls.company.id,
            'default_location_src_id': cls.production_loc.id,
            'default_location_dest_id': cls.bin_dest.id,
            'use_create_lots': True,
            'use_existing_lots': False,
            # `production_only` sengaja dibiarkan False supaya test ini hanya
            # menguji jalur lot; `_is_gr_prod()` cuma melihat `move_type_sap`.
            'move_type_sap': cls.prod_in_move_type,
        })
        cls.type_int = cls.env['stock.picking.type'].create({
            'name': 'GRLOT Bin to Bin',
            'sequence_code': 'GRLOTINT',
            'code': 'internal',
            'warehouse_id': cls.warehouse.id,
            'company_id': cls.company.id,
            'default_location_src_id': cls.warehouse.lot_stock_id.id,
            'default_location_dest_id': cls.bin_dest.id,
            'use_create_lots': True,
            'use_existing_lots': True,
            'move_type_sap': False,
        })

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _make_picking(self, picking_type, qty=100.0, product=None, keep_lines=False):
        product = product or self.product
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': picking_type.default_location_src_id.id,
            'location_dest_id': picking_type.default_location_dest_id.id,
            'company_id': self.company.id,
            'move_ids': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
                'location_id': picking_type.default_location_src_id.id,
                'location_dest_id': picking_type.default_location_dest_id.id,
                'company_id': self.company.id,
            })],
        })
        picking.action_confirm()
        if not keep_lines:
            picking.move_line_ids.unlink()
        return picking

    def _barcode_create_line(self, picking, qty=100.0, lot_name=False,
                             production_line=None, product=None):
        """Tiruan `_createCommandVals()` milik stock_barcode.

        `lot_name` di sini persis yang dikirim client setelah operator men-scan
        barcode asing: core mengisinya lewat `updateLotName()`.
        """
        product = product or self.product
        picking.write({'move_line_ids': [(0, 0, {
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
            'lot_id': False,
            'lot_name': lot_name,
            'package_id': False,
            'picking_id': picking.id,
            'picked': True,
            'product_id': product.id,
            'product_uom_id': product.uom_id.id,
            'production_line_id': production_line.id if production_line else False,
            'quantity': qty,
            'state': 'assigned',
        })]})
        return picking.move_line_ids.sorted('id')[-1]

    def _qr_lots(self):
        return self.env['stock.lot'].search([('name', 'like', '%|%')])

    # ==================================================================
    # 1. create()
    # ==================================================================
    def test_create_drops_scanned_lot_name_on_gr_prod(self):
        """Baris GR yang dibuat dengan `lot_name` hasil scan: nama itu dibuang."""
        picking = self._make_picking(self.type_gr)
        before = self._qr_lots()

        line = self._barcode_create_line(
            picking, lot_name=SCANNED_QR, production_line=self.production_line,
        )

        self.assertFalse(
            line.lot_name,
            "lot_name hasil scan QR PO SAP masih tersimpan (%r)" % line.lot_name,
        )
        self.assertEqual(
            line.lot_id.name, self.expected_lot_name,
            "Nama lot tidak berasal dari _get_or_create_lot() (dapat %r)"
            % line.lot_id.name,
        )
        self.assertEqual(
            self._qr_lots(), before,
            "Ada stock.lot baru yang namanya mengandung '|'",
        )

    def test_create_keeps_lot_name_on_non_gr_picking(self):
        """Regresi: operation type non-GR tetap boleh memakai `lot_name`.

        Checker IN, adjustment, dsb. memang mengandalkan mekanisme core ini.
        """
        picking = self._make_picking(self.type_int)

        line = self._barcode_create_line(picking, lot_name='GRLOT-MANUAL-1')

        self.assertEqual(
            line.lot_name, 'GRLOT-MANUAL-1',
            "lot_name pada picking non-GR ikut dibuang",
        )

    # ==================================================================
    # 2. write()
    # ==================================================================
    def test_write_drops_scanned_lot_name_on_gr_prod(self):
        """Scan QR setelah baris ada -> `write({'lot_name': ...})` diabaikan."""
        picking = self._make_picking(self.type_gr)
        line = self._barcode_create_line(picking, production_line=self.production_line)

        line.write({'lot_name': SCANNED_QR})

        self.assertFalse(
            line.lot_name,
            "lot_name hasil scan QR PO SAP tersimpan lewat write() (%r)" % line.lot_name,
        )
        self.assertEqual(line.lot_id.name, self.expected_lot_name)

    def test_write_mixed_recordset_only_strips_gr_prod_lines(self):
        """Recordset campuran: hanya baris GR yang kehilangan `lot_name`."""
        gr_picking = self._make_picking(self.type_gr)
        int_picking = self._make_picking(self.type_int)
        gr_line = self._barcode_create_line(
            gr_picking, production_line=self.production_line,
        )
        int_line = self._barcode_create_line(int_picking)

        (gr_line | int_line).write({'lot_name': SCANNED_QR})

        self.assertFalse(gr_line.lot_name, "Baris GR masih menyimpan lot_name")
        self.assertEqual(
            int_line.lot_name, SCANNED_QR,
            "Baris non-GR ikut kehilangan lot_name padahal boleh memakainya",
        )

    # ==================================================================
    # 3. _action_done()
    # ==================================================================
    def test_validate_generates_lot_even_when_write_hook_skipped(self):
        """Inilah lubang yang melahirkan lot `160110003526|71`.

        Baris dibuat client SEBELUM operator men-scan production line, jadi
        `create()` tidak bisa membuat lot. Hook `write()` pun tidak jalan karena
        syaratnya `production_line_id AND expiration_date`, sedangkan produk ini
        tanpa masa simpan. Dulu sisanya diserahkan ke core, yang memakai
        `lot_name` mentah hasil scan. Sekarang `_action_done()` yang menutupnya.
        """
        picking = self._make_picking(self.type_gr)
        line = self._barcode_create_line(picking, lot_name=SCANNED_QR)
        self.assertFalse(line.lot_id, "Prasyarat test: baris belum punya lot")

        # Baris `lot_name` sudah dibuang di create(); kembalikan lewat SQL-level
        # write supaya kondisi awal bug (lot_name liar masih menempel) benar-benar
        # tereproduksi, bukan cuma lolos karena lapis pertama.
        line.invalidate_recordset()
        self.env.cr.execute(
            "UPDATE stock_move_line SET lot_name = %s WHERE id = %s",
            (SCANNED_QR, line.id),
        )
        line.invalidate_recordset(['lot_name'])
        self.assertEqual(line.lot_name, SCANNED_QR)

        line.write({'production_line_id': self.production_line.id})
        self.assertFalse(
            line.lot_id,
            "Prasyarat test: hook write() memang tidak boleh mengisi lot di sini",
        )

        before = self._qr_lots()
        picking.button_validate()

        self.assertEqual(picking.state, 'done')
        self.assertEqual(
            line.lot_id.name, self.expected_lot_name,
            "Validate memakai nama lot hasil scan, bukan format Production Code "
            "(dapat %r)" % line.lot_id.name,
        )
        self.assertFalse(line.lot_name, "lot_name liar tidak dibersihkan")
        self.assertEqual(
            self._qr_lots(), before,
            "Validate melahirkan stock.lot yang namanya mengandung '|'",
        )

    # ==================================================================
    # 4. Nama lot harus mengikuti production line yang BENAR
    # ==================================================================
    def test_no_inherit_production_line_from_virtual_source_location(self):
        """Quant di lokasi `Production` tidak boleh mewarnai baris GR baru.

        Reproduksi GR PO 160110003473: baris hasil `action_confirm()` mewarisi
        `production_line_id` dari salah satu quant jurnal-lawan (semuanya
        negatif) di lokasi virtual `Production`, lalu `create()` memakai nilai
        itu untuk menamai lot -- sebelum production line yang sebenarnya
        sempat ditulis.
        """
        self.env['stock.quant'].create({
            'product_id': self.product.id,
            'location_id': self.production_loc.id,
            'quantity': -1280.0,
            'production_line_id': self.production_line_2.id,
        })

        picking = self._make_picking(self.type_gr, keep_lines=True)
        line = picking.move_line_ids

        self.assertTrue(line, "Prasyarat test: action_confirm() harus membuat move line")
        self.assertFalse(
            line.production_line_id,
            "Baris GR mewarisi production line %s dari quant jurnal-lawan di "
            "lokasi virtual" % line.production_line_id.display_name,
        )
        self.assertFalse(
            line.lot_id,
            "Lot terbentuk dari production line hasil warisan (dapat %r)"
            % line.lot_id.name,
        )

    def test_lot_regenerated_when_production_line_corrected(self):
        """Ganti production line -> nama lot ikut berganti, bukan mengunci lot lama.

        `action_picking_po_sap()` menulis production line yang benar SETELAH
        baris terbentuk. Dulu `_get_or_create_lot()` punya fallback
        `search([('id','=',self.lot_id.id)])` yang mengembalikan lot lama begitu
        nama baru belum ada di database -- jadi koreksinya tidak pernah terjadi.
        """
        picking = self._make_picking(self.type_gr, product=self.product_exp)
        line = self._barcode_create_line(
            picking, product=self.product_exp, production_line=self.production_line,
        )
        self.assertEqual(line.lot_id.name, 'UT-GR-P1')
        first_lot = line.lot_id

        line.write({'production_line_id': self.production_line_2.id})

        self.assertEqual(
            line.lot_id.name, 'UT-GR-P9',
            "Nama lot tidak ikut dikoreksi saat production line diganti "
            "(masih %r)" % line.lot_id.name,
        )
        self.assertNotEqual(line.lot_id, first_lot)
        self.assertEqual(
            line.lot_id.production_line_id, self.production_line_2,
            "production_line_id pada lot tidak ikut yang benar",
        )

    def test_validate_blocks_gr_line_without_production_line(self):
        """Tanpa production line, lot tidak bisa dinamai -> tolak dengan jelas.

        Lebih baik Validate gagal daripada stok masuk dengan nama lot karangan
        yang harus dibersihkan manual belakangan.
        """
        picking = self._make_picking(self.type_gr)
        line = self._barcode_create_line(picking, lot_name=SCANNED_QR)
        self.env.cr.execute(
            "UPDATE stock_move_line SET lot_name = %s WHERE id = %s",
            (SCANNED_QR, line.id),
        )
        line.invalidate_recordset(['lot_name'])

        with self.assertRaises(ValidationError) as ctx:
            picking.button_validate()

        self.assertIn('Production Line', str(ctx.exception))
        self.assertNotEqual(picking.state, 'done')
