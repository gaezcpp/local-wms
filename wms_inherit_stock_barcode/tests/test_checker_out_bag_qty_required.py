"""Uji validasi baru: Checker Out (`picking_type_id.checker_out`) wajib mengisi
`bag_qty` sebelum `button_validate()`.

Direproduksi dari kejadian nyata **S00864** (DB_WMS_DEV_008, company 1601):
picking CO `FINI/CO/26/6069/864` bisa divalidasi walau `bag_qty` seluruh
move line-nya masih 0 -- scan langsung dari package (entire pack) mengisi
`quantity` dari isi package tanpa pernah menyentuh `bag_qty`, dan
`_sync_post_validate_quantities()` baru mengisinya balik SESUDAH picking
'done'. Untuk Checker Out, mengisi bag_qty adalah langkah verifikasi manual
(hitung fisik per bag) yang harus terjadi SEBELUM validate -- kalau tidak,
pengecekan itu tidak pernah benar-benar terjadi.

Produk uji SENGAJA tidak diberi `uom_bag_id`/`uom_pallet_id` dan tidak lewat
package/pallet sama sekali -- fokus test ini murni pada syarat "bag_qty
terisi", bukan konversi bag/pallet (yang sudah dites terpisah di
`test_split_qty_pallet_bag_uom.py`). Tanpa `uom_bag_id`,
`_sync_qty_from_bag()` tidak melakukan apa-apa (lihat
`stock_move_line.py:156-168`), jadi menulis `bag_qty` di sini tidak
memicu efek samping apa pun selain field itu sendiri.

Jalankan:
    python odoo-bin -c wms.conf -d DB_WMS_DEV_008 --test-enable --stop-after-init \\
        --test-tags /wms_inherit_stock_barcode:TestCheckerOutBagQtyRequired
"""

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'wms_outbound')
class TestCheckerOutBagQtyRequired(TransactionCase):

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

        cls.type_co = cls.env['stock.picking.type'].search([
            ('company_id', '=', cls.company.id),
            ('sequence_code', '=', 'CO'),
        ], limit=1)
        if not cls.type_co:
            raise ValueError("Operation type CO untuk company %s tidak ditemukan." % cls.company.name)
        if not cls.type_co.checker_out:
            raise ValueError("Operation type CO company %s harus checker_out=True untuk test ini." % cls.company.name)

        cls.product = cls.env['product.product'].create({
            'name': 'UT Checker Out Bag Qty',
            'default_code': 'UT-CO-BAGQTY',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'none',
        })

        cls.loc_src = cls.type_co.default_location_src_id
        cls.loc_dest = cls.type_co.default_location_dest_id

    def _make_co_picking(self, qty):
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.type_co.id,
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
        })
        picking.action_confirm()
        return picking

    def _make_result_package(self, name):
        return self.env['stock.package'].create({'name': name, 'company_id': self.company.id})

    def test_01_scan_without_bag_qty_blocks_validate(self):
        """Quantity terisi (hasil scan/reservasi) tapi `bag_qty` masih 0 --
        persis kondisi S00864 -- harus ditolak sebelum validate."""
        self.env['stock.quant']._update_available_quantity(self.product, self.loc_src, 100.0)

        picking = self._make_co_picking(100.0)
        picking.action_assign()
        picking.move_line_ids.write({
            'picked': True,
            'result_package_id': self._make_result_package('UT-CO-PLT-01').id,
        })

        self.assertEqual(picking.move_line_ids.quantity, 100.0)
        self.assertEqual(picking.move_line_ids.bag_qty, 0.0)

        with self.assertRaisesRegex(ValidationError, "Stock Package: UT-CO-PLT-01"):
            picking.button_validate()
        self.assertNotEqual(picking.state, 'done')

    def test_02_filling_bag_qty_allows_validate(self):
        """Setelah `bag_qty` diisi, validate harus berhasil seperti biasa."""
        self.env['stock.quant']._update_available_quantity(self.product, self.loc_src, 100.0)

        picking = self._make_co_picking(100.0)
        picking.action_assign()
        picking.move_line_ids.write({
            'picked': True,
            'result_package_id': self._make_result_package('UT-CO-PLT-02').id,
            'bag_qty': 5.0,
        })

        res = picking.button_validate()
        self.assertNotIsInstance(res, dict)
        self.assertEqual(picking.state, 'done')

    def test_03_zero_quantity_line_does_not_require_bag_qty(self):
        """Line belum discan (`picked=False`) tidak wajib `bag_qty`."""
        self.env['stock.quant']._update_available_quantity(self.product, self.loc_src, 100.0)

        picking = self._make_co_picking(100.0)
        picking.action_assign()
        self.assertEqual(picking.move_line_ids.quantity, 100.0)
        self.assertFalse(picking.move_line_ids.picked)

        picking._check_checker_out_bag_qty()

    def test_04_non_checker_out_picking_type_unaffected(self):
        """Operation type yang BUKAN Checker Out tidak boleh kena wajib bag_qty."""
        # Operation type ad-hoc (bukan PICK/CO nyata) supaya bebas dari
        # syarat lain yang tidak relevan di sini (uu_only, mandatory_destination,
        # dst) -- satu-satunya hal yang diuji adalah checker_out=False.
        type_plain = self.env['stock.picking.type'].create({
            'name': 'UT Plain Internal (not checker_out)',
            'sequence_code': 'UTPLN',
            'code': 'internal',
            'warehouse_id': self.type_co.warehouse_id.id,
            'company_id': self.company.id,
            'default_location_src_id': self.loc_src.id,
            'default_location_dest_id': self.loc_dest.id,
            'checker_out': False,
        })
        self.assertFalse(type_plain.checker_out, "Prasyarat: operation type ini bukan Checker Out.")

        self.env['stock.quant']._update_available_quantity(self.product, self.loc_src, 100.0)

        picking = self.env['stock.picking'].create({
            'picking_type_id': type_plain.id,
            'location_id': type_plain.default_location_src_id.id,
            'location_dest_id': type_plain.default_location_dest_id.id,
            'company_id': self.company.id,
        })
        self.env['stock.move'].create({
            'picking_id': picking.id,
            'product_id': self.product.id,
            'product_uom_qty': 100.0,
            'product_uom': self.product.uom_id.id,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
            'company_id': self.company.id,
        })
        picking.action_confirm()
        picking.action_assign()
        picking.move_line_ids.write({'picked': True})

        self.assertEqual(picking.move_line_ids.quantity, 100.0)
        self.assertEqual(picking.move_line_ids.bag_qty, 0.0)
        res = picking.button_validate()
        self.assertNotIsInstance(res, dict)
        self.assertEqual(picking.state, 'done')
