from unittest.mock import patch

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
