"""Verifikasi alur asli: GR FG dari QR Scanner, dua production line berbeda.

Berbeda dengan `test_gr_prod_lot_name.py` yang memakai fixture buatan sendiri,
file ini menjalankan **method produksi yang sebenarnya** --
`production.order.sap.action_picking_po_sap_from_qr()` -- di atas data nyata
DB_WMS_DEV_008, persis seperti yang dilakukan operator lewat menu QR Scanner
GR FG. Tujuannya menjawab satu pertanyaan: PO 160110003473 di-GR dengan line
`71` lalu line `95`, apakah keduanya benar-benar mendapat `stock.lot` yang
berbeda?

Kejadian aslinya (27/08/2026): `1601/In-Prod-FG/26/02580` (line 71) dan
`1601/In-Prod-FG/26/02581` (line 95) sama-sama memakai lot
`3965732 - 18022028` -- lot milik line **94**, yang tidak dipakai sama sekali.
Dua sebabnya:

1. `action_confirm()` membuat move line lebih dulu, dan `_fill_from_source_quant()`
   mewarisi `production_line_id` dari salah satu ratusan quant jurnal-lawan
   (semuanya negatif) di lokasi virtual `Production`. Yang menang quant id
   terkecil dengan qty terbesar -- kebetulan milik line 94.
2. `action_picking_po_sap()` baru menulis production line yang benar SETELAH
   itu, tapi `_get_or_create_lot()` punya fallback yang mengembalikan lot yang
   sudah menempel di baris begitu nama hasil format belum ada di database.
   Jadi koreksinya tidak pernah terjadi.

Test ini `TransactionCase`, jadi picking/lot yang terbentuk di-rollback penuh
dan tidak tertinggal di database (sudah diverifikasi lewat query langsung).
Satu efek samping yang tidak ikut di-rollback: nomor urut `stock.picking`
memakai sequence PostgreSQL, jadi tiap kali test ini jalan ada 2 nomor
`1601/In-Prod-FG/...` yang terpakai dan menjadi lompatan. Tidak berbahaya, tapi
jangan dijalankan berulang-ulang di database produksi.

Jalankan:

    D:\\CPP\\Odoo19-ENT\\python\\python.exe odoo-bin -c wms.conf \\
        -u wms_base_warehouse --test-enable --test-tags wms_gr_lot_live \\
        --stop-after-init --no-http
"""

import logging

from odoo.tests import TransactionCase, tagged

_logger = logging.getLogger(__name__)

PO_NUMBER = '160110003473'
LINE_CODE_A = '71'
LINE_CODE_B = '95'
# Lot yang salah pada kejadian aslinya (milik production line 94).
WRONG_LOT_NAME = '3965732 - 18022028'


@tagged('post_install', '-at_install', 'wms_gr_lot_live')
class TestGrProdLotNameLive(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.po_sap = cls.env['production.order.sap'].sudo().search(
            [('po_number', '=', PO_NUMBER)], limit=1
        )
        if not cls.po_sap:
            raise ValueError("PO SAP %s tidak ada di database ini." % PO_NUMBER)

        cls.company = cls.po_sap.company_id
        cls.env.user.write({
            'company_ids': [(4, cls.company.id)],
            'company_id': cls.company.id,
        })
        cls.env = cls.env(context=dict(
            cls.env.context, allowed_company_ids=[cls.company.id],
        ))

        ProductionLine = cls.env['production.line'].sudo()
        cls.line_a = ProductionLine.search([
            ('code', '=', LINE_CODE_A), ('company_id', '=', cls.company.id),
        ], limit=1)
        cls.line_b = ProductionLine.search([
            ('code', '=', LINE_CODE_B), ('company_id', '=', cls.company.id),
        ], limit=1)
        if not cls.line_a or not cls.line_b:
            raise ValueError("Production line %s / %s tidak ada untuk company %s."
                             % (LINE_CODE_A, LINE_CODE_B, cls.company.name))

    # ------------------------------------------------------------------
    def _gr_from_qr(self, line_code):
        """Jalankan menu QR Scanner GR FG, kembalikan picking yang dibuka."""
        pickings_before = self.env['stock.picking'].sudo().search(
            [('po_sap_id', '=', self.po_sap.id)]
        )
        self.env['production.order.sap'].action_picking_po_sap_from_qr(
            PO_NUMBER, line_code,
        )
        pickings_after = self.env['stock.picking'].sudo().search(
            [('po_sap_id', '=', self.po_sap.id)]
        )
        new_picking = pickings_after - pickings_before
        self.assertEqual(
            len(new_picking), 1,
            "Scan QR line %s harus menghasilkan tepat satu picking baru" % line_code,
        )
        return new_picking

    # ------------------------------------------------------------------
    def test_two_production_lines_get_two_different_lots(self):
        picking_a = self._gr_from_qr(LINE_CODE_A)
        line_a = picking_a.move_line_ids
        self.assertTrue(line_a, "Picking GR line %s tidak punya move line" % LINE_CODE_A)

        picking_b = self._gr_from_qr(LINE_CODE_B)
        line_b = picking_b.move_line_ids
        self.assertTrue(line_b, "Picking GR line %s tidak punya move line" % LINE_CODE_B)

        _logger.info(
            "[GR-LOT-LIVE] %s line %s (prod_code %s) -> lot %r | %s line %s "
            "(prod_code %s) -> lot %r",
            picking_a.name, LINE_CODE_A, self.line_a.prod_code,
            line_a.lot_id.mapped('name'),
            picking_b.name, LINE_CODE_B, self.line_b.prod_code,
            line_b.lot_id.mapped('name'),
        )

        # 1. Production line pada baris memang yang di-scan, bukan warisan quant.
        self.assertEqual(
            line_a.production_line_id, self.line_a,
            "Baris GR line %s malah memakai production line %s"
            % (LINE_CODE_A, line_a.production_line_id.mapped('code')),
        )
        self.assertEqual(
            line_b.production_line_id, self.line_b,
            "Baris GR line %s malah memakai production line %s"
            % (LINE_CODE_B, line_b.production_line_id.mapped('code')),
        )

        # 2. Lot-nya menempel pada production line yang SEPADAN.
        #    Bukan `assertEqual` ke line yang di-scan: begitu lot dengan nama
        #    hasil format sudah ada, `_get_or_create_lot()` memakainya kembali,
        #    dan `stock.lot.production_line_id` menyimpan line yang pertama
        #    membuatnya. Karena format hanya memakai `prod_code[-1]`, line 94 dan
        #    95 (prod_code sama-sama `9`) memang berbagi satu lot -- itu
        #    konsekuensi format yang diterima, bukan bug. Yang wajib benar
        #    adalah digit prod_code-nya.
        for line, scanned in ((line_a, self.line_a), (line_b, self.line_b)):
            self.assertEqual(
                str(line.lot_id.production_line_id.prod_code)[-1],
                str(scanned.prod_code)[-1],
                "Lot %r menempel pada production line %s (prod_code %s), tidak "
                "sepadan dengan line %s (prod_code %s) yang di-scan"
                % (line.lot_id.name, line.lot_id.production_line_id.code,
                   line.lot_id.production_line_id.prod_code,
                   scanned.code, scanned.prod_code),
            )

        # 3. Dua line dengan prod_code berbeda -> dua lot berbeda.
        self.assertNotEqual(
            line_a.lot_id, line_b.lot_id,
            "Line %s dan %s masih berbagi lot %r"
            % (LINE_CODE_A, LINE_CODE_B, line_a.lot_id.name),
        )
        self.assertNotEqual(line_a.lot_id.name, line_b.lot_id.name)

        # 4. Digit prod_code di dalam nama lot sesuai line masing-masing.
        #    Format `production.code`: shift[-1] + group_code + prod_code[-1] + ...
        #    GR lewat menu ini jalan dengan sudo(), jadi group_code kosong dan
        #    digit prod_code jatuh di indeks 1.
        prod_code_digit_a = str(self.line_a.prod_code)[-1]
        prod_code_digit_b = str(self.line_b.prod_code)[-1]
        self.assertNotEqual(
            prod_code_digit_a, prod_code_digit_b,
            "Prasyarat test: prod_code line %s dan %s harus berbeda"
            % (LINE_CODE_A, LINE_CODE_B),
        )
        self.assertEqual(
            line_a.lot_id.name[1], prod_code_digit_a,
            "Nama lot line %s (%r) tidak memuat prod_code %r"
            % (LINE_CODE_A, line_a.lot_id.name, prod_code_digit_a),
        )
        self.assertEqual(
            line_b.lot_id.name[1], prod_code_digit_b,
            "Nama lot line %s (%r) tidak memuat prod_code %r"
            % (LINE_CODE_B, line_b.lot_id.name, prod_code_digit_b),
        )

        # 5. Regresi eksplisit terhadap kejadian aslinya.
        self.assertNotEqual(
            line_a.lot_id.name, WRONG_LOT_NAME,
            "Line %s masih memakai lot milik line 94" % LINE_CODE_A,
        )
