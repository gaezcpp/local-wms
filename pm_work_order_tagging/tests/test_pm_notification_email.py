from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'pm_work_order')
class TestPmNotificationEmail(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.parent_equipment = cls.env['maintenance.equipment'].create({
            'name': 'PM Notification Parent',
            'company_id': cls.company.id,
        })
        cls.equipment = cls.env['maintenance.equipment'].create({
            'name': 'PM Notification Equipment',
            'company_id': cls.company.id,
        })
        with patch.object(
            type(cls.env['tagging.record']),
            '_send_email_to_department',
            return_value=True,
        ):
            cls.tagging = cls.env['tagging.record'].create({
                'tagger_name': 'PM Notification Test',
                'company_id': cls.company.id,
                'parent_equipment_id': cls.parent_equipment.id,
                'equipment_id': cls.equipment.id,
                'status': 'validated',
            })
        cls.notification_type = cls.env['tagging.type.notification'].create({
            'name': 'M1',
            'desc': 'Corrective maintenance notification',
            'company_id': cls.company.id,
        })
        cls.env['ir.config_parameter'].sudo().set_param(
            'notification_tagging_email_to',
            'planner@example.com',
        )

    def test_confirm_queues_maintenance_planner_email(self):
        wizard = self.env['pm.notification.wizard'].create({
            'tagging_id': self.tagging.id,
            'company_id': self.company.id,
            'tagging_type_notification_id': self.notification_type.id,
            'notification_desc': self.notification_type.desc,
        })
        template_model = type(self.env['mail.template'])

        with patch.object(template_model, 'send_mail', return_value=1) as send_mail:
            wizard.action_confirm()

        self.assertEqual(self.tagging.status, 'waiting_sap')
        self.assertEqual(
            self.tagging.tagging_type_notification_id,
            self.notification_type,
        )
        send_mail.assert_called_once()
        self.assertEqual(send_mail.call_args.args[0], self.tagging.id)
        email_values = send_mail.call_args.kwargs['email_values']
        self.assertEqual(email_values['email_to'], 'planner@example.com')
        self.assertFalse(email_values['model'])
        self.assertFalse(email_values['res_id'])

    def test_confirm_fails_when_email_cannot_be_queued(self):
        wizard = self.env['pm.notification.wizard'].create({
            'tagging_id': self.tagging.id,
            'company_id': self.company.id,
            'tagging_type_notification_id': self.notification_type.id,
            'notification_desc': self.notification_type.desc,
        })
        template_model = type(self.env['mail.template'])

        with self.assertRaises(ValidationError), patch.object(
            template_model,
            'send_mail',
            side_effect=RuntimeError('Queue unavailable'),
        ):
            wizard.action_confirm()

    def test_confirm_requires_notification_email_parameter(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'notification_tagging_email_to',
            '',
        )
        wizard = self.env['pm.notification.wizard'].create({
            'tagging_id': self.tagging.id,
            'company_id': self.company.id,
            'tagging_type_notification_id': self.notification_type.id,
            'notification_desc': self.notification_type.desc,
        })

        with self.assertRaisesRegex(
            ValidationError,
            'notification_tagging_email_to',
        ):
            wizard.action_confirm()
