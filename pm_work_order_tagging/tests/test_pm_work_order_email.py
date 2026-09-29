from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'pm_work_order')
class TestPmWorkOrderEmail(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.department = cls.env['tagging.department'].create({
            'name': 'Maintenance Test',
            'company_id': cls.company.id,
            'department_type': 'planner',
        })
        cls.env['tagging.pic'].create({
            'email': 'maintenance@example.com',
            'department_ids': [(6, 0, cls.department.ids)],
        })
        with patch.object(
            type(cls.env['tagging.record']),
            '_send_email_to_department',
            return_value=True,
        ):
            cls.tagging = cls.env['tagging.record'].create({
                'tagger_name': 'Email Test',
                'department_id': cls.department.id,
                'company_id': cls.company.id,
            })

    def test_non_planning_sap_work_order_queues_email_once(self):
        template_model = type(self.env['mail.template'])
        with patch.object(template_model, 'send_mail', return_value=1) as send_mail:
            work_order = self.env['pm.work.order'].create({
                'wo_sap': '900000100',
                'tagging_id': self.tagging.id,
                'company_id': self.company.id,
                'sap_synchronize': True,
            })
            work_order._send_creation_email_to_department()

        self.assertTrue(work_order.creation_email_sent)
        send_mail.assert_called_once()
        self.assertEqual(
            send_mail.call_args.kwargs['email_values']['email_to'],
            'maintenance@example.com',
        )
        self.assertFalse(
            send_mail.call_args.kwargs['email_values']['auto_delete']
        )
        self.assertFalse(send_mail.call_args.kwargs['email_values']['model'])
        self.assertFalse(send_mail.call_args.kwargs['email_values']['res_id'])

    def test_planning_work_order_does_not_queue_email(self):
        template_model = type(self.env['mail.template'])
        with patch.object(template_model, 'send_mail', return_value=1) as send_mail:
            work_order = self.env['pm.work.order'].create({
                'wo_sap': '900000101',
                'tagging_id': self.tagging.id,
                'company_id': self.company.id,
                'is_maintenance_plan': True,
                'sap_synchronize': True,
            })

        self.assertFalse(work_order.creation_email_sent)
        send_mail.assert_not_called()

    def test_sap_work_order_without_tagging_uses_maintenance_department(self):
        template_model = type(self.env['mail.template'])
        with patch.object(template_model, 'send_mail', return_value=1) as send_mail:
            work_order = self.env['pm.work.order'].create({
                'wo_sap': '900000105',
                'company_id': self.company.id,
                'sap_synchronize': True,
            })

        self.assertTrue(work_order.creation_email_sent)
        send_mail.assert_called_once()
        self.assertEqual(
            send_mail.call_args.kwargs['email_values']['email_to'],
            'maintenance@example.com',
        )

    def test_existing_work_order_queues_email_when_sap_number_arrives(self):
        work_order = self.env['pm.work.order'].create({
            'tagging_id': self.tagging.id,
            'company_id': self.company.id,
        })
        template_model = type(self.env['mail.template'])
        with patch.object(template_model, 'send_mail', return_value=1) as send_mail:
            work_order.write({
                'wo_sap': '900000102',
                'sap_synchronize': True,
            })

        self.assertTrue(work_order.creation_email_sent)
        send_mail.assert_called_once()

    def test_manual_sap_number_does_not_queue_email(self):
        template_model = type(self.env['mail.template'])
        with patch.object(template_model, 'send_mail', return_value=1) as send_mail:
            work_order = self.env['pm.work.order'].create({
                'wo_sap': '900000103',
                'tagging_id': self.tagging.id,
                'company_id': self.company.id,
            })

        self.assertFalse(work_order.creation_email_sent)
        send_mail.assert_not_called()

    def test_failed_queue_can_be_retried(self):
        template_model = type(self.env['mail.template'])
        with patch.object(
            template_model,
            'send_mail',
            side_effect=[RuntimeError('mail unavailable'), 1],
        ) as send_mail:
            work_order = self.env['pm.work.order'].create({
                'wo_sap': '900000104',
                'tagging_id': self.tagging.id,
                'company_id': self.company.id,
                'sap_synchronize': True,
            })
            self.assertFalse(work_order.creation_email_sent)
            work_order._send_creation_email_to_department()

        self.assertTrue(work_order.creation_email_sent)
        self.assertEqual(send_mail.call_count, 2)

    def _create_confirmed_work_order(self, **values):
        work_order_values = {
            'wo_sap': '900000200',
            'tagging_id': self.tagging.id,
            'company_id': self.company.id,
            'state': 'waiting_sap',
            'description': 'Technical report test',
        }
        work_order_values.update(values)
        with patch.object(
            type(self.env['pm.work.order']),
            '_send_creation_email_to_department',
            return_value=True,
        ):
            work_order = self.env['pm.work.order'].create(work_order_values)
        work_order.action_close()
        return work_order

    @staticmethod
    def _rendered_confirm_email(work_order):
        return {
            work_order.id: {
                'auto_delete': True,
                'body_html': '<p>Technical report submitted</p>',
                'email_cc': False,
                'email_from': 'noreply@example.com',
                'mail_server_id': False,
                'reply_to': False,
                'scheduled_date': False,
                'subject': f'Technical Report {work_order.wo_sap}',
            },
        }

    def test_confirm_queues_email_once(self):
        work_order = self._create_confirmed_work_order()
        self.assertEqual(work_order.state, 'confirm')

        mail_model = type(self.env['mail.mail'])
        template_model = type(self.env['mail.template'])
        with patch.object(
            template_model,
            '_generate_template',
            return_value=self._rendered_confirm_email(work_order),
        ), patch.object(
            mail_model,
            'create',
            autospec=True,
            return_value=self.env['mail.mail'].browse([1]),
        ) as create_mail:
            self.env['pm.work.order'].cron_queue_confirm_emails()
            self.env['pm.work.order'].cron_queue_confirm_emails()

        create_mail.assert_called_once()
        mail_values = create_mail.call_args.args[-1][0]
        self.assertEqual(mail_values['email_to'], 'maintenance@example.com')
        self.assertFalse(mail_values['auto_delete'])
        self.assertFalse(mail_values['model'])
        self.assertFalse(mail_values['res_id'])
        self.assertTrue(work_order.confirm_email_sent)

    def test_confirm_email_template_renders_work_order_details(self):
        work_order = self._create_confirmed_work_order()
        template = self.env.ref(
            'pm_work_order_tagging.mail_template_pm_technical_report_submitted',
        )

        rendered = template._generate_template(
            work_order.ids,
            ('body_html', 'subject'),
        )[work_order.id]

        self.assertIn(work_order.wo_sap, rendered['subject'])
        self.assertIn(work_order.wo_sap, rendered['body_html'])
        self.assertIn(self.env.user.display_name, rendered['body_html'])
        self.assertIn('Technical Report Status:', rendered['body_html'])
        self.assertIn('Submitted', rendered['body_html'])

    def test_failed_confirm_email_queue_is_retried(self):
        work_order = self._create_confirmed_work_order(wo_sap='900000201')
        mail_model = type(self.env['mail.mail'])
        template_model = type(self.env['mail.template'])
        rendered = self._rendered_confirm_email(work_order)

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
            self.env['pm.work.order'].cron_queue_confirm_emails()

        self.assertFalse(work_order.confirm_email_sent)

        with patch.object(
            template_model,
            '_generate_template',
            return_value=rendered,
        ), patch.object(
            mail_model,
            'create',
            autospec=True,
            return_value=self.env['mail.mail'].browse([1]),
        ):
            self.env['pm.work.order'].cron_queue_confirm_emails()

        self.assertTrue(work_order.confirm_email_sent)

    def test_confirm_email_planner_is_isolated_by_company(self):
        other_company = self.env['res.company'].create({
            'name': 'Other Confirm Company',
        })
        other_department = self.env['tagging.department'].create({
            'name': 'Other Planner',
            'company_id': other_company.id,
            'department_type': 'planner',
        })
        self.env['tagging.pic'].create({
            'email': 'other-planner@example.com',
            'department_id': other_department.id,
        })
        own_work_order = self._create_confirmed_work_order(wo_sap='900000202')
        other_work_order = self._create_confirmed_work_order(
            wo_sap='900000203',
            company_id=other_company.id,
            tagging_id=False,
        )
        rendered = {
            **self._rendered_confirm_email(own_work_order),
            **self._rendered_confirm_email(other_work_order),
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
            self.env['pm.work.order'].cron_queue_confirm_emails()

        recipients_by_subject = {
            values['subject']: values['email_to']
            for values in create_mail.call_args.args[-1]
        }
        self.assertEqual(
            recipients_by_subject['Technical Report 900000202'],
            'maintenance@example.com',
        )
        self.assertEqual(
            recipients_by_subject['Technical Report 900000203'],
            'other-planner@example.com',
        )

    def test_draft_reminder_includes_pending_duration(self):
        with patch.object(
            type(self.env['pm.work.order']),
            '_send_creation_email_to_department',
            return_value=True,
        ):
            work_order = self.env['pm.work.order'].create({
                'wo_sap': '900000300',
                'company_id': self.company.id,
            })
        reminder_time = work_order.create_date + timedelta(days=3, hours=2)

        mail_model = type(self.env['mail.mail'])
        with patch.object(
            fields.Datetime,
            'now',
            return_value=reminder_time,
        ), patch.object(
            mail_model,
            'create',
            autospec=True,
            return_value=self.env['mail.mail'].browse([1]),
        ) as create_mail:
            self.env['pm.work.order'].cron_reminder_wo_draft()

        create_mail.assert_called_once()
        mail_values = create_mail.call_args.args[-1][0]
        self.assertEqual(mail_values['email_to'], 'maintenance@example.com')
        self.assertFalse(mail_values['auto_delete'])
        self.assertIn('900000300', mail_values['body_html'])
        self.assertIn('Pending Duration', mail_values['body_html'])
        self.assertIn('3 days', mail_values['body_html'])
