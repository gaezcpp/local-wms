from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "pm_work_order_security")
class TestPmSecurity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.production_department = cls.env["tagging.department"].create({
            "name": "Production Security Test",
            "company_id": cls.company.id,
            "department_type": "production",
        })
        cls.maintenance_department = cls.env["tagging.department"].create({
            "name": "Maintenance Security Test",
            "company_id": cls.company.id,
            "department_type": "maintenance",
        })
        with patch.object(
            type(cls.env["tagging.record"]),
            "_send_email_to_department",
            return_value=True,
        ):
            cls.production_tagging = cls.env["tagging.record"].create({
                "tagger_name": "Production Security Test",
                "company_id": cls.company.id,
                "department_id": cls.production_department.id,
                "plant_code": "SECURITY-TEST",
            })
            cls.maintenance_tagging = cls.env["tagging.record"].create({
                "tagger_name": "Maintenance Security Test",
                "company_id": cls.company.id,
                "department_id": cls.maintenance_department.id,
                "plant_code": "SECURITY-TEST",
            })
        cls.production_sparepart = cls.env["tagging.wo.sparepart"].create({
            "record_id": cls.production_tagging.id,
            "remarks": "Production",
        })
        cls.maintenance_sparepart = cls.env["tagging.wo.sparepart"].create({
            "record_id": cls.maintenance_tagging.id,
            "remarks": "Maintenance",
        })
        production_group = cls.env.ref(
            "pm_work_order_tagging.group_tagging_work_order_production"
        )
        cls.production_user = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create({
            "name": "Production Security User",
            "login": "production-security-user",
            "company_id": cls.company.id,
            "company_ids": [Command.link(cls.company.id)],
            "group_ids": [Command.link(production_group.id)],
        })

    def test_production_user_only_sees_production_tagging(self):
        tagging = self.env["tagging.record"].with_user(self.production_user)

        visible = tagging.search([
            ("id", "in", (self.production_tagging | self.maintenance_tagging).ids)
        ])

        self.assertEqual(visible, self.production_tagging)
        with self.assertRaises(AccessError):
            self.maintenance_tagging.with_user(self.production_user).check_access("read")

    def test_production_user_cannot_reclassify_departments(self):
        departments = self.env["tagging.department"].with_user(self.production_user)

        self.assertEqual(
            departments.search([
                (
                    "id",
                    "in",
                    (self.production_department | self.maintenance_department).ids,
                )
            ]),
            self.production_department,
        )
        with self.assertRaises(AccessError):
            self.production_department.with_user(self.production_user).write({
                "department_type": "maintenance",
            })
        with self.assertRaises(AccessError):
            departments.create({
                "name": "Forbidden Department",
                "company_id": self.company.id,
                "department_type": "production",
            })

    def test_production_user_cannot_create_or_write_maintenance_tagging(self):
        tagging = self.env["tagging.record"].with_user(self.production_user)

        with patch.object(
            type(tagging),
            "_send_email_to_department",
            return_value=True,
        ), self.assertRaises(AccessError):
            tagging.create({
                "tagger_name": "Forbidden Maintenance Tagging",
                "company_id": self.company.id,
                "department_id": self.maintenance_department.id,
            })

        with self.assertRaises(AccessError):
            self.maintenance_tagging.with_user(self.production_user).write({
                "description": "Forbidden update",
            })

    def test_production_dashboard_respects_record_rule(self):
        stats = self.env["tagging.record"].with_user(
            self.production_user
        ).get_dashboard_stats({
            "date_range": "today",
            "plant_code": "SECURITY-TEST",
        })

        self.assertEqual(stats["kpi"]["total"], 1)

    def test_production_user_only_sees_production_spareparts(self):
        spareparts = self.env["tagging.wo.sparepart"].with_user(
            self.production_user
        ).search([
            (
                "id",
                "in",
                (self.production_sparepart | self.maintenance_sparepart).ids,
            )
        ])

        self.assertEqual(spareparts, self.production_sparepart)
