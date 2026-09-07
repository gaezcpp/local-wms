"""Uji `sale.order.action_confirm()`: auto-isi `rumus_gratis` untuk pasangan
order+gratis produk yang sama.

Direproduksi dari kejadian nyata SO **S00865** (DB_WMS_DEV_008): line order
qty 100 dan line gratis qty 5 untuk produk yang sama, tapi `rumus_gratis`
kedua line-nya tetap 0 -- tidak ada satu pun jalur cron yang pernah
mengisinya, jadi `stock.move._reallocate_gratis_final_pair()` selalu
menghitung `qty_gratis = 0` (dibagi rumus_gratis 0 di-guard jadi 0) dan
Final tidak pernah benar-benar membagi order/gratis.

Formula (dari help text field `rumus_gratis`): `floor(order_qty / gratis_qty)
+ 1`, contoh order 100 gratis 5 -> 20+1=21.

Jalankan:
    python odoo-bin -c wms.conf -d DB_WMS_DEV_008 --test-enable --stop-after-init \\
        --test-tags /wms_sale_order_sap:TestAssignOrderSelectionRumusGratis
"""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'wms_gratis')
class TestAssignOrderSelectionRumusGratis(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.partner = cls.env['res.partner'].create({'name': 'UT Rumus Gratis Customer'})
        cls.product = cls.env['product.product'].create({
            'name': 'UT Rumus Gratis Product',
            'default_code': 'UT-RUMUS-GRATIS',
            'type': 'consu',
            'is_storable': True,
        })

    def _make_order(self, order_qty, gratis_qty):
        return self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [
                (0, 0, {'product_id': self.product.id, 'product_uom_qty': order_qty}),
                (0, 0, {'product_id': self.product.id, 'product_uom_qty': gratis_qty}),
            ],
        })

    def test_01_computes_rumus_gratis_for_order_gratis_pair(self):
        """order 100 + gratis 5 -> floor(100/5)+1 = 21, persis contoh S00865."""
        order = self._make_order(100.0, 5.0)
        order.action_confirm()

        order_line = order.order_line.filtered(lambda l: l.order_selection == 'order')
        gratis_line = order.order_line.filtered(lambda l: l.order_selection == 'gratis')
        self.assertEqual(order_line.product_uom_qty, 100.0)
        self.assertEqual(gratis_line.product_uom_qty, 5.0)
        self.assertEqual(order_line.rumus_gratis, 21)
        self.assertEqual(gratis_line.rumus_gratis, 21)

    def test_02_field_help_example_order_200_gratis_8(self):
        """Contoh persis di help text field: order 200 gratis 8 -> 25+1=26."""
        order = self._make_order(200.0, 8.0)
        order.action_confirm()

        self.assertEqual(set(order.order_line.mapped('rumus_gratis')), {26})

    def test_03_single_line_no_gratis_leaves_rumus_gratis_untouched(self):
        """Tanpa pasangan gratis, tidak ada apa pun yang perlu dihitung --
        rumus_gratis tidak boleh diisi angka sembarangan."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [
                (0, 0, {'product_id': self.product.id, 'product_uom_qty': 100.0}),
            ],
        })
        order.action_confirm()

        self.assertEqual(order.order_line.order_selection, 'order')
        self.assertEqual(order.order_line.rumus_gratis, 0)

    def test_04_recomputes_when_qty_changes_before_confirm(self):
        """Confirm menghitung dari qty terakhir sebelum dokumen jadi sale."""
        order = self._make_order(100.0, 5.0)

        order_line = order.order_line.filtered(lambda l: l.product_uom_qty == 100.0)
        order_line.product_uom_qty = 200.0
        order.action_confirm()

        # order 200 gratis 5 -> floor(200/5)+1 = 41.
        self.assertEqual(set(order.order_line.mapped('rumus_gratis')), {41})
