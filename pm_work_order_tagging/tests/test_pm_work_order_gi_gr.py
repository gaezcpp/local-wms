"""Uji aturan GI/GR pada PM Work Order.

Aturan baru (menggantikan gate ``is_header_valid``):

* ``RSNUM`` membuat line material; ``KZEAR = 'X'`` menandai ``is_gi = True``.
* ``BANFN`` membuat line jasa;     ``KZABN = 'X'`` menandai ``is_gr = True``.
* Line tetap dibuat walau GI/GR belum selesai, jadi progres tetap terlihat.
* ``action_waiting_sap`` menolak submit selama masih ada material yang
  belum GI atau jasa yang belum GR.

Jalankan:
    python odoo-bin -c wms.conf -d DB_WMS_DEV_008 --test-enable --stop-after-init
        --test-tags /pm_work_order_tagging:TestPmWorkOrderGiGr
"""

import base64

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'pm_work_order')
class TestPmWorkOrderGiGr(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = cls.env.company
        cls.company.sudo().write({'sync_pm': True})

        cls.analysis = cls.env['pm.analysis'].create({
            'name': 'Analisa Uji',
            'code': 'UJI',
            'need_desc': False,
            'company_id': cls.company.id,
        })
        cls.sparepart = cls.env['tagging.spare_part'].create({
            'name': 'Bearing Uji',
            'sku': 'SKU-UJI-1',
            'company_id': cls.company.id,
        })
        cls.work_order = cls.env['pm.work.order'].create({
            'company_id': cls.company.id,
            'wo_sap': '900000001',
        })

    # ------------------------------------------------------------------
    # helper
    # ------------------------------------------------------------------
    def _fill_close_evidence(self, work_order):
        """Isi field wajib selain GI/GR supaya validasi berhenti di GI/GR."""
        work_order.write({
            'date_from': '2026-08-01 01:00:00',
            'date_to': '2026-08-01 02:00:00',
            'analysis_id': self.analysis.id,
            'problem_handling': 'Sudah diperbaiki',
            'photo_attachment': base64.b64encode(b'foto'),
        })

    def _new_wo(self, materials=(), jasas=()):
        work_order = self.env['pm.work.order'].create({
            'company_id': self.company.id,
            'wo_sap': '900000002',
        })
        self._fill_close_evidence(work_order)
        for idx, is_gi in enumerate(materials):
            self.env['pm.work.order.material.line'].create({
                'pm_work_order_id': work_order.id,
                'product_sparepart_id': self.sparepart.id,
                'product_material': 'SKU-UJI-%s' % idx,
                'quantity': 1.0,
                'gi_doc': '100%s' % idx,
                'is_gi': is_gi,
            })
        for idx, is_gr in enumerate(jasas):
            self.env['pm.work.order.jasa.line'].create({
                'pm_work_order_id': work_order.id,
                'material_desc': 'Jasa %s' % idx,
                'gr_doc': '200%s' % idx,
                'is_gr': is_gr,
            })
        return work_order

    def _sync(self, rows, work_order=None):
        work_order = work_order or self.work_order
        work_order._sync_sap_work_order_lines(work_order, rows, self.company)
        work_order.invalidate_recordset()
        return work_order

    # ------------------------------------------------------------------
    # sinkronisasi line dari data SAP
    # ------------------------------------------------------------------
    def test_rsnum_tanpa_kzear_tetap_buat_line_is_gi_false(self):
        wo = self._sync([{
            'RSNUM': '4711',
            'MATNR': 'SKU-UJI-1',
            'MAKTX': 'Bearing Uji',
            'ENMNG': '2',
            'KZEAR': '',
        }])
        self.assertEqual(len(wo.pm_wo_material_line_ids), 1)
        line = wo.pm_wo_material_line_ids
        self.assertFalse(line.is_gi)
        self.assertEqual(line.gi_doc, '4711')
        self.assertEqual(line.quantity, 2.0)

    def test_rsnum_dengan_kzear_x_membuat_is_gi_true(self):
        wo = self._sync([{
            'RSNUM': '4711',
            'MATNR': 'SKU-UJI-1',
            'MAKTX': 'Bearing Uji',
            'ENMNG': '2',
            'KZEAR': 'X',
        }])
        self.assertTrue(wo.pm_wo_material_line_ids.is_gi)

    def test_banfn_tanpa_kzabn_tetap_buat_line_is_gr_false(self):
        wo = self._sync([{
            'BANFN': '5811',
            'TXZ01': 'Jasa Servis',
            'SKU': 'JSA-1',
            'KZABN': '',
        }])
        self.assertEqual(len(wo.pm_wo_jasa_line_ids), 1)
        self.assertFalse(wo.pm_wo_jasa_line_ids.is_gr)
        self.assertEqual(wo.pm_wo_jasa_line_ids.gr_doc, '5811')

    def test_banfn_dengan_kzabn_x_membuat_is_gr_true(self):
        wo = self._sync([{
            'BANFN': '5811',
            'TXZ01': 'Jasa Servis',
            'SKU': 'JSA-1',
            'KZABN': 'X',
        }])
        self.assertTrue(wo.pm_wo_jasa_line_ids.is_gr)

    def test_satu_baris_rsnum_dan_banfn_dinilai_terpisah(self):
        """KZEAR 'X' tidak lagi harus barengan dengan KZABN 'X'."""
        wo = self._sync([{
            'RSNUM': '4711',
            'MATNR': 'SKU-UJI-1',
            'MAKTX': 'Bearing Uji',
            'ENMNG': '1',
            'KZEAR': 'X',
            'BANFN': '5811',
            'TXZ01': 'Jasa Servis',
            'SKU': 'JSA-1',
            'KZABN': '',
        }])
        self.assertTrue(wo.pm_wo_material_line_ids.is_gi)
        self.assertFalse(wo.pm_wo_jasa_line_ids.is_gr)

    def test_sync_ulang_memperbarui_flag_tanpa_duplikat_line(self):
        rows = [{
            'RSNUM': '4711',
            'MATNR': 'SKU-UJI-1',
            'MAKTX': 'Bearing Uji',
            'ENMNG': '1',
            'KZEAR': '',
            'BANFN': '5811',
            'TXZ01': 'Jasa Servis',
            'SKU': 'JSA-1',
            'KZABN': '',
        }]
        wo = self._sync(rows)
        self.assertFalse(wo.pm_wo_material_line_ids.is_gi)
        self.assertFalse(wo.pm_wo_jasa_line_ids.is_gr)

        rows[0].update({'KZEAR': 'X', 'KZABN': 'X'})
        wo = self._sync(rows)
        self.assertEqual(len(wo.pm_wo_material_line_ids), 1)
        self.assertEqual(len(wo.pm_wo_jasa_line_ids), 1)
        self.assertTrue(wo.pm_wo_material_line_ids.is_gi)
        self.assertTrue(wo.pm_wo_jasa_line_ids.is_gr)

    def test_baris_tanpa_rsnum_dan_banfn_diabaikan(self):
        wo = self._sync([{'MATNR': 'SKU-UJI-1', 'KZEAR': 'X', 'KZABN': 'X'}])
        self.assertFalse(wo.pm_wo_material_line_ids)
        self.assertFalse(wo.pm_wo_jasa_line_ids)

    # ------------------------------------------------------------------
    # validasi action_waiting_sap
    # ------------------------------------------------------------------
    def test_submit_ditolak_jika_material_belum_semua_gi(self):
        wo = self._new_wo(materials=(True, False))
        with self.assertRaises(ValidationError) as err:
            wo.action_waiting_sap()
        self.assertIn('belum GI', err.exception.args[0])
        self.assertEqual(wo.state, 'draft')

    def test_submit_ditolak_jika_jasa_belum_semua_gr(self):
        wo = self._new_wo(jasas=(True, False))
        with self.assertRaises(ValidationError) as err:
            wo.action_waiting_sap()
        self.assertIn('belum GR', err.exception.args[0])
        self.assertEqual(wo.state, 'draft')

    def test_submit_ditolak_jika_material_dan_jasa_belum_selesai(self):
        wo = self._new_wo(materials=(False,), jasas=(False,))
        with self.assertRaises(ValidationError) as err:
            wo.action_waiting_sap()
        self.assertIn('belum GI', err.exception.args[0])
        self.assertIn('belum GR', err.exception.args[0])
        self.assertEqual(wo.state, 'draft')

    def test_submit_lolos_jika_semua_gi_dan_gr_selesai(self):
        wo = self._new_wo(materials=(True, True), jasas=(True,))
        wo.action_waiting_sap()
        self.assertEqual(wo.state, 'waiting_sap')

    def test_submit_lolos_jika_hanya_material_dan_semua_gi(self):
        wo = self._new_wo(materials=(True,))
        wo.action_waiting_sap()
        self.assertEqual(wo.state, 'waiting_sap')

    def test_submit_lolos_jika_tanpa_material_dan_jasa(self):
        wo = self._new_wo()
        wo.action_waiting_sap()
        self.assertEqual(wo.state, 'waiting_sap')

    # ------------------------------------------------------------------
    # flag tampilan notebook
    # ------------------------------------------------------------------
    def test_flag_material_jasa_mengikuti_keberadaan_line(self):
        wo = self._new_wo(materials=(False,), jasas=(False,))
        self.assertTrue(wo.material_only)
        self.assertTrue(wo.jasa_only)

        kosong = self._new_wo()
        self.assertFalse(kosong.material_only)
        self.assertFalse(kosong.jasa_only)

    # ------------------------------------------------------------------
    # gate tampilan Close Evidence
    # ------------------------------------------------------------------
    def test_gi_gr_done_false_selama_ada_material_belum_gi(self):
        wo = self._new_wo(materials=(True, False))
        self.assertFalse(wo.gi_gr_done)

    def test_gi_gr_done_false_selama_ada_jasa_belum_gr(self):
        wo = self._new_wo(materials=(True,), jasas=(False,))
        self.assertFalse(wo.gi_gr_done)

    def test_gi_gr_done_true_jika_semua_selesai_atau_tanpa_line(self):
        self.assertTrue(self._new_wo(materials=(True,), jasas=(True,)).gi_gr_done)
        self.assertTrue(self._new_wo().gi_gr_done)

    def test_gi_gr_done_ikut_berubah_saat_line_di_gi(self):
        wo = self._new_wo(materials=(False,))
        self.assertFalse(wo.gi_gr_done)
        wo.pm_wo_material_line_ids.is_gi = True
        self.assertTrue(wo.gi_gr_done)
