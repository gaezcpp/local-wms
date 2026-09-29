from unittest.mock import patch

from odoo.exceptions import UserError
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
        cls.planner_department = cls.env['tagging.department'].create({
            'name': 'Maintenance Planner',
            'company_id': cls.company.id,
            'department_type': 'planner',
        })
        cls.env['tagging.pic'].create({
            'email': 'planner@example.com',
            'department_id': cls.planner_department.id,
        })
        cls.env['tagging.pic'].create({
            'email': 'PLANNER@example.com, SECOND@example.com',
            'department_ids': [(6, 0, cls.planner_department.ids)],
        })

    def _create_wizard(self):
        return self.env['pm.notification.wizard'].create({
            'tagging_id': self.tagging.id,
            'company_id': self.company.id,
            'tagging_type_notification_id': self.notification_type.id,
            'notification_desc': self.notification_type.desc,
        })

    def test_confirm_waits_for_notification_number(self):
        wizard = self._create_wizard()
        template_model = type(self.env['mail.template'])

        with patch.object(template_model, 'send_mail', return_value=1) as send_mail:
            wizard.action_confirm()

        self.assertEqual(self.tagging.status, 'waiting_sap')
        self.assertEqual(
            self.tagging.tagging_type_notification_id,
            self.notification_type,
        )
        send_mail.assert_not_called()
        self.assertFalse(self.tagging.notification_email_queued)

    def test_number_write_queues_email_once(self):
        self._create_wizard().action_confirm()
        mail_model = type(self.env['mail.mail'])
        template_model = type(self.env['mail.template'])
        with patch.object(mail_model, 'create', autospec=True) as create_mail:
            self.tagging.write({'nomor_notifikasi': '10001234'})

        create_mail.assert_not_called()
        rendered = {
            self.tagging.id: {
                'auto_delete': True,
                'body_html': '<p>Notification 10001234</p>',
                'email_cc': False,
                'email_from': 'noreply@example.com',
                'mail_server_id': False,
                'reply_to': False,
                'scheduled_date': False,
                'subject': 'Notification 10001234',
            },
        }

        with patch.object(
            template_model,
            '_generate_template',
            return_value=rendered,
        ), patch.object(
            mail_model,
            'create',
            autospec=True,
            return_value=self.env['mail.mail'].browse([1]),
        ) as create_mail:
            self.env['tagging.record'].cron_queue_pm_notification_emails()
            self.env['tagging.record'].cron_queue_pm_notification_emails()

        create_mail.assert_called_once()
        mail_values = create_mail.call_args.args[-1][0]
        self.assertEqual(
            mail_values['email_to'],
            'planner@example.com,second@example.com',
        )
        self.assertFalse(mail_values['auto_delete'])
        self.assertFalse(mail_values['model'])
        self.assertFalse(mail_values['res_id'])
        self.assertTrue(self.tagging.notification_email_queued)

    def test_failed_queue_is_retried(self):
        self._create_wizard().action_confirm()
        self.tagging.write({'nomor_notifikasi': '10001234'})
        mail_model = type(self.env['mail.mail'])
        template_model = type(self.env['mail.template'])
        rendered = {
            self.tagging.id: {
                'auto_delete': True,
                'body_html': '<p>Notification 10001234</p>',
                'email_cc': False,
                'email_from': 'noreply@example.com',
                'mail_server_id': False,
                'reply_to': False,
                'scheduled_date': False,
                'subject': 'Notification 10001234',
            },
        }

        with patch.object(
            template_model,
            '_generate_template',
            return_value=rendered,
        ), patch.object(
            mail_model,
            'create',
            autospec=True,
            side_effect=RuntimeError('Queue unavailable'),
        ):
            self.env['tagging.record'].cron_queue_pm_notification_emails()

        self.assertEqual(self.tagging.nomor_notifikasi, '10001234')
        self.assertFalse(self.tagging.notification_email_queued)

        with patch.object(
            template_model,
            '_generate_template',
            return_value=rendered,
        ), patch.object(
            mail_model,
            'create',
            autospec=True,
            return_value=self.env['mail.mail'].browse([1]),
        ) as create_mail:
            self.env['tagging.record'].cron_queue_pm_notification_emails()

        create_mail.assert_called_once()
        self.assertTrue(self.tagging.notification_email_queued)

    def test_closed_record_can_mark_notification_email_queued(self):
        self.tagging.write({
            'nomor_notifikasi': '10001234',
            'status': 'closed',
        })
        rendered = {
            self.tagging.id: {
                'auto_delete': True,
                'body_html': '<p>Notification 10001234</p>',
                'email_cc': False,
                'email_from': 'noreply@example.com',
                'mail_server_id': False,
                'reply_to': False,
                'scheduled_date': False,
                'subject': 'Notification 10001234',
            },
        }
        mail_model = type(self.env['mail.mail'])
        template_model = type(self.env['mail.template'])

        with patch.object(
            template_model,
            '_generate_template',
            return_value=rendered,
        ), patch.object(
            mail_model,
            'create',
            autospec=True,
            return_value=self.env['mail.mail'].browse([1]),
        ) as create_mail:
            self.env['tagging.record'].cron_queue_pm_notification_emails()

        create_mail.assert_called_once()
        self.assertTrue(self.tagging.notification_email_queued)
        self.assertEqual(self.tagging.status, 'closed')
        with self.assertRaises(UserError):
            self.tagging.write({'tagger_name': 'Blocked Edit'})
        normal_user_tagging = self.tagging.with_user(
            self.env.ref('base.user_admin')
        )
        with self.assertRaises(UserError):
            normal_user_tagging.write({'notification_email_queued': False})

    def test_missing_planner_recipient_remains_pending(self):
        wizard = self._create_wizard()
        wizard.action_confirm()
        self.tagging.write({'nomor_notifikasi': '10001234'})
        self.planner_department.active = False
        mail_model = type(self.env['mail.mail'])

        with patch.object(mail_model, 'create', autospec=True) as create_mail:
            self.env['tagging.record'].cron_queue_pm_notification_emails()

        self.assertEqual(self.tagging.status, 'waiting_sap')
        create_mail.assert_not_called()
        self.assertFalse(self.tagging.notification_email_queued)

    def test_planner_recipients_are_isolated_by_company(self):
        other_company = self.env['res.company'].create({
            'name': 'Other Planner Company',
        })
        other_department = self.env['tagging.department'].create({
            'name': 'Other Maintenance Planner',
            'company_id': other_company.id,
            'department_type': 'planner',
        })
        self.env['tagging.pic'].create({
            'email': 'other-planner@example.com',
            'department_id': other_department.id,
        })
        with patch.object(
            type(self.env['tagging.record']),
            '_send_email_to_department',
            return_value=True,
        ):
            other_tagging = self.env['tagging.record'].sudo().create({
                'tagger_name': 'Other PM Notification Test',
                'company_id': other_company.id,
                'status': 'waiting_sap',
                'nomor_notifikasi': '20001234',
            })
            no_planner_company = self.env['res.company'].create({
                'name': 'No Planner Company',
            })
            no_planner_tagging = self.env['tagging.record'].sudo().create({
                'tagger_name': 'No Planner PM Notification Test',
                'company_id': no_planner_company.id,
                'status': 'waiting_sap',
                'nomor_notifikasi': '30001234',
            })
        self._create_wizard().action_confirm()
        self.tagging.write({'nomor_notifikasi': '10001234'})
        rendered = {
            record.id: {
                'auto_delete': True,
                'body_html': '<p>Notification</p>',
                'email_cc': False,
                'email_from': 'noreply@example.com',
                'mail_server_id': False,
                'reply_to': False,
                'scheduled_date': False,
                'subject': f'Notification {record.nomor_notifikasi}',
            }
            for record in self.tagging | other_tagging
        }
        mail_model = type(self.env['mail.mail'])
        template_model = type(self.env['mail.template'])

        with patch.object(
            template_model,
            '_generate_template',
            return_value=rendered,
        ), patch.object(
            mail_model,
            'create',
            autospec=True,
            return_value=self.env['mail.mail'].browse([1, 2]),
        ) as create_mail:
            self.env['tagging.record'].cron_queue_pm_notification_emails()

        mail_values = create_mail.call_args.args[-1]
        recipients_by_subject = {
            values['subject']: values['email_to'] for values in mail_values
        }
        self.assertEqual(len(mail_values), 2)
        self.assertEqual(
            recipients_by_subject['Notification 10001234'],
            'planner@example.com,second@example.com',
        )
        self.assertEqual(
            recipients_by_subject['Notification 20001234'],
            'other-planner@example.com',
        )
        self.assertTrue(self.tagging.notification_email_queued)
        self.assertTrue(other_tagging.notification_email_queued)
        self.assertFalse(no_planner_tagging.notification_email_queued)
