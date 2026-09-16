from datetime import date, datetime, timedelta
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..models.pm_work_order import PlanMaintenanceWorkOrder


@tagged('post_install', '-at_install', 'pm_work_order')
class TestPmWorkOrderPreventifPlanning(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            'company_registry': f'TEST-PM-{cls.company.id}',
            'sync_pm': True,
        })
        cls.system = cls.env['tagging.system'].create({
            'name': 'Planning System',
            'code': 'PLANNING-SYSTEM',
            'company_id': cls.company.id,
        })
        cls.subsystem = cls.env['tagging.subsystem'].create({
            'name': 'Planning Subsystem',
            'code': 'PLANNING-SUBSYSTEM',
            'system_id': cls.system.id,
            'company_id': cls.company.id,
        })
        cls.parent_equipment = cls.env['maintenance.equipment'].create({
            'name': 'Planning Parent Equipment',
            'equipment_no': '10015600',
            'company_id': cls.company.id,
            'system_id': cls.system.id,
            'sub_system_id': cls.subsystem.id,
        })
        cls.equipment = cls.env['maintenance.equipment'].create({
            'name': 'Planning Sub Equipment',
            'equipment_no': '10015650',
            'company_id': cls.company.id,
            'parent_equipment_id': cls.parent_equipment.id,
            'system_id': cls.system.id,
            'sub_system_id': cls.subsystem.id,
        })
        cls.model = cls.env['pm.work.order']

    def _row(self, nplda='20260915', tsenq='', aufnr='000000000003'):
        return {
            'WARPL': '000000001234',
            'NPLDA': nplda,
            'EQUNR': '00010015650',
            'WERKS': self.company.company_registry,
            'AUFNR': aufnr,
            'TSENQ': tsenq,
        }

    def _run_cron(self, rows):
        with (
            patch.object(PlanMaintenanceWorkOrder, '_fetch_sap_data', return_value=rows),
            patch.object(
                PlanMaintenanceWorkOrder,
                'today_jakarta',
                return_value=date(2026, 9, 14),
            ),
        ):
            self.model.cron_synhronize_sap_preventif_planning_wo()

    def _run_inspection_cron(self, rows):
        with patch.object(
            PlanMaintenanceWorkOrder,
            '_fetch_sap_data',
            return_value=rows,
        ):
            self.model.cron_synhronize_sap_preventif_inspection()

    def _planning_domain(self, planning_date=date(2026, 9, 15)):
        date_from = self.model._parse_string_datetime(planning_date.strftime('%Y%m%d'), '')
        date_to = date_from + timedelta(days=1)
        return [
            ('start_time', '>=', date_from),
            ('start_time', '<', date_to),
            ('equipment_id', '=', self.parent_equipment.id),
            ('system_id', '=', self.system.id),
            ('sub_system_id', '=', self.subsystem.id),
            ('sub_equipment_id', '=', self.equipment.id),
        ]

    def test_future_row_created_once_and_existing_row_skipped(self):
        self._run_cron([self._row()])
        work_order = self.model.search(self._planning_domain())
        self.assertEqual(len(work_order), 1)
        self.assertEqual(work_order.wo_sap, '3')
        self.assertEqual(work_order.start_time, datetime(2026, 9, 14, 17))

        self._run_cron([self._row(aufnr='000000000004')])
        work_order = self.model.search(self._planning_domain())
        self.assertEqual(len(work_order), 1)
        self.assertEqual(work_order.wo_sap, '3')

    def test_nplda_requires_yyyymmdd_format(self):
        self._run_cron([self._row(nplda='2026915')])

        self.assertFalse(self.model.search(self._planning_domain()))

    def test_planning_links_sap_wo_then_inspection_updates_same_record(self):
        self._run_cron([self._row(aufnr='')])
        work_order = self.model.search(self._planning_domain())
        self.assertFalse(work_order.wo_sap)

        self._run_cron([self._row()])
        self.assertEqual(work_order.wo_sap, '3')

        inspection_row = self._row()
        inspection_row.update({
            'AUART': 'ZLS4',
            'KTEXT': 'Preventif inspection',
            'PRIOKX': 'MEDIUM',
        })
        self._run_inspection_cron([inspection_row])

        matching_work_orders = self.model.search([
            ('company_id', '=', self.company.id),
            ('wo_sap', '=', '3'),
        ])
        self.assertEqual(matching_work_orders, work_order)
        self.assertEqual(work_order.description, 'Preventif inspection')

    def test_exact_sap_payload_sets_wo_sap(self):
        other_companies = self.env['res.company'].search([
            ('id', '!=', self.company.id),
            ('company_registry', '=', '1321'),
        ])
        other_companies.write({'sync_pm': False})
        self.company.company_registry = '1321'
        equipment = self.env['maintenance.equipment'].create({
            'name': 'CPB-LPG-01-06-001',
            'equipment_no': '10015661',
            'company_id': self.company.id,
            'parent_equipment_id': self.parent_equipment.id,
            'system_id': self.system.id,
            'sub_system_id': self.subsystem.id,
        })
        payload = {
            'WARPL': '080000000065',
            'NPLDA': '20310305',
            'AUFNR': '',
            'TPLNR': 'CPB-LPG-01-06-001',
            'EQUNR': '000000000010015661',
            'TSENQ': '',
            'IWERK': '1321',
        }

        self._run_cron([payload])
        work_order = self.model.search([
            ('company_id', '=', self.company.id),
            ('maintenance_plan_number', '=', '80000000065'),
            ('sub_equipment_id', '=', equipment.id),
        ])
        self.assertEqual(len(work_order), 1)
        self.assertFalse(work_order.wo_sap)

        payload['AUFNR'] = '013214000627'
        self._run_cron([payload])

        self.assertEqual(self.model.search_count([
            ('company_id', '=', self.company.id),
            ('maintenance_plan_number', '=', '80000000065'),
            ('sub_equipment_id', '=', equipment.id),
        ]), 1)
        self.assertEqual(work_order.wo_sap, '13214000627')

    def test_matching_tsenq_x_deletes_existing_row(self):
        self._run_cron([self._row()])
        work_order = self.model.search(self._planning_domain())

        self._run_cron([self._row(tsenq='X')])

        self.assertFalse(work_order.exists())

    def test_past_row_not_created_and_older_than_two_days_deleted(self):
        expired = self.model.create({
            'company_id': self.company.id,
            'system_id': self.system.id,
            'sub_system_id': self.subsystem.id,
            'equipment_id': self.parent_equipment.id,
            'sub_equipment_id': self.equipment.id,
            'start_time': self.model._parse_string_datetime('20260911', ''),
        })

        self._run_cron([
            self._row(nplda='20260911'),
            self._row(nplda='20260913'),
        ])

        self.assertFalse(expired.exists())
        self.assertFalse(self.model.search(self._planning_domain(date(2026, 9, 13))))
