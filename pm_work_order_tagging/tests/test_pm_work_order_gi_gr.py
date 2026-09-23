"""Uji aturan GI/GR pada PM Work Order.

Aturan baru (menggantikan gate ``is_header_valid``):

* ``RSNUM`` membuat line material; ``KZEAR = 'X'`` menandai ``is_gi = True``.
* ``BANFN`` membuat line jasa;     ``KZABN = 'X'`` menandai ``is_gr = True``.
* Line tetap dibuat walau GI/GR belum selesai, jadi progres tetap terlihat.
* ``action_waiting_sap`` menolak submit selama masih ada material yang
  belum GI atau jasa yang belum GR.

Jalankan:
    python odoo-bin -c <feed-config> -d DB_WMS_DEV_009 --test-enable --stop-after-init
        --test-tags /pm_work_order_tagging:TestPmWorkOrderGiGr
"""

import base64
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from ..models.pm_work_order import PlanMaintenanceWorkOrder


@tagged('post_install', '-at_install', 'pm_work_order')
class TestPmWorkOrderGiGr(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = cls.env.company
        cls.company.sudo().write({
            'company_registry': f'TEST-GI-GR-{cls.company.id}',
            'sync_pm': True,
        })
        cls.system = cls.env['tagging.system'].create({
            'name': 'System Uji GI GR',
            'code': f'SYS-GI-GR-{cls.company.id}',
            'company_id': cls.company.id,
        })
        cls.subsystem = cls.env['tagging.subsystem'].create({
            'name': 'Subsystem Uji GI GR',
            'code': f'SUB-GI-GR-{cls.company.id}',
            'system_id': cls.system.id,
            'company_id': cls.company.id,
        })
        cls.parent_equipment = cls.env['maintenance.equipment'].create({
            'name': 'Equipment Induk Uji GI GR',
            'equipment_no': f'GI-GR-P-{cls.company.id}',
            'company_id': cls.company.id,
            'system_id': cls.system.id,
            'sub_system_id': cls.subsystem.id,
        })
        cls.equipment = cls.env['maintenance.equipment'].create({
            'name': 'Equipment Uji GI GR',
            'equipment_no': f'GI-GR-C-{cls.company.id}',
            'company_id': cls.company.id,
            'parent_equipment_id': cls.parent_equipment.id,
            'system_id': cls.system.id,
            'sub_system_id': cls.subsystem.id,
        })
        cls.tagging = cls.env['tagging.record'].create({
            'name': f'TAG-GI-GR-{cls.company.id}',
            'tagger_name': 'Unit Test',
            'company_id': cls.company.id,
            'system_id': cls.system.id,
            'sub_system_id': cls.subsystem.id,
            'parent_equipment_id': cls.parent_equipment.id,
            'equipment_id': cls.equipment.id,
        })

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

    def _cron_row(self, **values):
        row = {
            'AUFNR': '00000900000001',
            'AUART': 'ZM01',
            'PRIOKX': 'NORMAL',
            'WERKS': self.company.company_registry,
            'KTEXT': 'Work order unit test',
            'STRMN': '20260916',
            'STRUR': '080000',
            'LTRMN': '20260916',
            'LTRUR': '090000',
            'XLOEK': 'X',
            'RSNUM': '4711',
            'RSPOS': '0010',
            'MATNR': self.sparepart.sku,
            'MAKTX': self.sparepart.name,
            'ENMNG': '1',
            'KZEAR': '',
        }
        row.update(values)
        return row

    def _run_cron(self, method_name, rows):
        with patch.object(
            PlanMaintenanceWorkOrder,
            '_fetch_sap_data',
            return_value=rows,
        ):
            getattr(self.env['pm.work.order'], method_name)()

    # ------------------------------------------------------------------
    # sinkronisasi line dari data SAP
    # ------------------------------------------------------------------
    def test_rsnum_tanpa_kzear_tetap_buat_line_is_gi_false(self):
        wo = self._sync([{
            'RSNUM': '4711',
            'RSPOS': '0010',
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
            'RSPOS': '0010',
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
            'RSPOS': '0010',
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
            'RSPOS': '0010',
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

    def test_cron_tagging_hapus_material_saat_kzear_kosong_xloek_x(self):
        line = self.env['pm.work.order.material.line'].create({
            'pm_work_order_id': self.work_order.id,
            'product_sparepart_id': self.sparepart.id,
            'product_material': self.sparepart.sku,
            'quantity': 1.0,
            'gi_doc': '4711',
            'item_number': '0010',
        })
        self.work_order.write({'tagging_id': self.tagging.id})
        row = self._cron_row(FETXT=self.tagging.name)

        self._run_cron('cron_synhronize_sap_tagging_work_order', [row])

        self.assertFalse(line.exists())

    def test_cron_tagging_uses_non_empty_fetxt_from_group(self):
        rows = [
            self._cron_row(FETXT=''),
            self._cron_row(FETXT=self.tagging.name, RSPOS='0011'),
        ]

        self._run_cron('cron_synhronize_sap_tagging_work_order', rows)

        work_order = self.env['pm.work.order'].search([
            ('tagging_id', '=', self.tagging.id),
            ('company_id', '=', self.company.id),
        ], limit=1)
        self.assertTrue(work_order)
        self.assertEqual(work_order.wo_sap, '900000001')

    def test_cron_work_order_hapus_material_saat_kzear_kosong_xloek_x(self):
        line = self.env['pm.work.order.material.line'].create({
            'pm_work_order_id': self.work_order.id,
            'product_sparepart_id': self.sparepart.id,
            'product_material': self.sparepart.sku,
            'quantity': 1.0,
            'gi_doc': '4711',
            'item_number': '0010',
        })
        row = self._cron_row(
            AUFNR='0000900000001',
            EQUNR=self.equipment.equipment_no,
        )

        self._run_cron('cron_synhronize_sap_work_order', [row])

        self.assertFalse(line.exists())

    def test_xloek_x_tidak_hapus_material_saat_kzear_x(self):
        wo = self._sync([self._cron_row(KZEAR='X')])

        self.assertEqual(len(wo.pm_wo_material_line_ids), 1)
        self.assertTrue(wo.pm_wo_material_line_ids.is_gi)

    def test_matnr_sama_item_number_berbeda_membuat_dua_line(self):
        wo = self._sync([
            {
                'RSNUM': '4711',
                'RSPOS': '0010',
                'MATNR': self.sparepart.sku,
                'MAKTX': self.sparepart.name,
                'BDMNG': '1',
            },
            {
                'RSNUM': '4711',
                'RSPOS': '0020',
                'MATNR': self.sparepart.sku,
                'MAKTX': self.sparepart.name,
                'BDMNG': '2',
            },
        ])

        self.assertEqual(len(wo.pm_wo_material_line_ids), 2)
        self.assertEqual(
            set(wo.pm_wo_material_line_ids.mapped('item_number')),
            {'0010', '0020'},
        )

    def test_item_number_sama_memperbarui_line_dan_detail(self):
        replacement_sparepart = self.env['tagging.spare_part'].create({
            'name': 'Bearing Pengganti',
            'sku': 'SKU-UJI-2',
            'company_id': self.company.id,
        })
        wo = self._sync([{
            'RSNUM': '4711',
            'RSPOS': '0010',
            'MATNR': self.sparepart.sku,
            'MAKTX': self.sparepart.name,
            'BDMNG': '1',
            'POTX1': 'Valuation Awal',
            'CHARG': 'Batch Awal',
        }])
        line_id = wo.pm_wo_material_line_ids.id

        wo = self._sync([{
            'RSNUM': '4711',
            'RSPOS': '0010',
            'MATNR': replacement_sparepart.sku,
            'MAKTX': replacement_sparepart.name,
            'BDMNG': '3',
            'POTX1': 'Valuation Baru',
            'CHARG': 'Batch Baru',
        }])

        line = wo.pm_wo_material_line_ids
        self.assertEqual(line.id, line_id)
        self.assertEqual(line.item_number, '0010')
        self.assertEqual(line.product_sparepart_id, replacement_sparepart)
        self.assertEqual(line.product_material, replacement_sparepart.sku)
        self.assertEqual(line.quantity, 3.0)
        self.assertEqual(line.valuation, 'Valuation Baru')
        self.assertEqual(line.material_detail, 'Batch Baru')

    def test_hapus_berdasarkan_item_number_bukan_matnr(self):
        rows = [
            {
                'RSNUM': '4711',
                'RSPOS': '0010',
                'MATNR': self.sparepart.sku,
                'MAKTX': self.sparepart.name,
                'BDMNG': '1',
            },
            {
                'RSNUM': '4711',
                'RSPOS': '0020',
                'MATNR': self.sparepart.sku,
                'MAKTX': self.sparepart.name,
                'BDMNG': '2',
            },
        ]
        wo = self._sync(rows)

        rows[1]['XLOEK'] = 'X'
        wo = self._sync(rows)

        self.assertEqual(len(wo.pm_wo_material_line_ids), 1)
        self.assertEqual(wo.pm_wo_material_line_ids.item_number, '0010')

    def test_material_tanpa_item_number_dilewati_tapi_jasa_tetap_dibuat(self):
        wo = self._sync([{
            'RSNUM': '4711',
            'MATNR': self.sparepart.sku,
            'BANFN': '5811',
            'TXZ01': 'Jasa Servis',
            'SKU': 'JSA-1',
        }])

        self.assertFalse(wo.pm_wo_material_line_ids)
        self.assertEqual(len(wo.pm_wo_jasa_line_ids), 1)

    def test_cron_tagging_material_aktif_menang_dari_histori_hapus(self):
        self.work_order.write({'tagging_id': self.tagging.id})
        active_sparepart = self.env['tagging.spare_part'].create({
            'name': 'SKF BEARING 6307 2Z',
            'sku': '110.04.0464',
            'company_id': self.company.id,
        })
        active_line = self.env['pm.work.order.material.line'].create({
            'pm_work_order_id': self.work_order.id,
            'product_sparepart_id': active_sparepart.id,
            'product_material': active_sparepart.sku,
            'quantity': 1.0,
            'gi_doc': '1284755',
            'sequence': 7,
            'item_number': '0010',
        })
        deleted_sparepart = self.env['tagging.spare_part'].create({
            'name': 'SKF BEARING 6309 2Z/C3',
            'sku': '110.04.1738',
            'company_id': self.company.id,
        })
        deleted_line = self.env['pm.work.order.material.line'].create({
            'pm_work_order_id': self.work_order.id,
            'product_sparepart_id': deleted_sparepart.id,
            'product_material': deleted_sparepart.sku,
            'quantity': 2.0,
            'gi_doc': '1284755',
            'item_number': '0020',
        })
        rows = [
            self._cron_row(
                AUFNR='013211000402',
                FETXT=self.tagging.name,
                MATNR=active_sparepart.sku,
                MAKTX=active_sparepart.name,
                BDMNG='2',
                ENMNG='0',
                RSNUM='0001284755',
                RSPOS='0010',
                POTX1='Valuation Aktif',
                CHARG='Detail Aktif',
                XLOEK='',
            ),
            self._cron_row(
                AUFNR='013211000402',
                FETXT=self.tagging.name,
                MATNR=deleted_sparepart.sku,
                MAKTX=deleted_sparepart.name,
                BDMNG='2',
                ENMNG='0',
                RSNUM='0001284755',
                RSPOS='0020',
            ),
            self._cron_row(
                AUFNR='013211000402',
                FETXT=self.tagging.name,
                MATNR=active_sparepart.sku,
                MAKTX=active_sparepart.name,
                BDMNG='1',
                ENMNG='0',
                RSNUM='0001284755',
                RSPOS='0010',
            ),
        ]

        self._run_cron('cron_synhronize_sap_tagging_work_order', rows)

        self.assertEqual(len(self.work_order.pm_wo_material_line_ids), 1)
        line = self.work_order.pm_wo_material_line_ids
        self.assertEqual(line.id, active_line.id)
        self.assertFalse(deleted_line.exists())
        self.assertEqual(line.product_material, active_sparepart.sku)
        self.assertEqual(line.quantity, 2.0)
        self.assertEqual(line.sequence, 7)
        self.assertEqual(line.valuation, 'Valuation Aktif')
        self.assertEqual(line.material_detail, 'Detail Aktif')
        self.assertFalse(line.is_gi)

        self._run_cron(
            'cron_synhronize_sap_tagging_work_order',
            list(reversed(rows)),
        )

        line = self.work_order.pm_wo_material_line_ids
        self.assertEqual(len(line), 1)
        self.assertEqual(line.id, active_line.id)
        self.assertEqual(line.quantity, 2.0)

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
