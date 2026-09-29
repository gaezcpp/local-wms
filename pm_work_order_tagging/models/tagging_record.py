import logging

from odoo import api, fields, models, tools
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class InheritTaggingRecord(models.Model):
    _inherit = 'tagging.record'

    tagging_type_notification_id = fields.Many2one(comodel_name='tagging.type.notification', string="Notification Type", tracking=True)
    notification_desc = fields.Text(string="Notification Desc", tracking=True)
    nomor_notifikasi = fields.Text(string="Nomor Notifikasi", tracking=True)
    notification_email_queued = fields.Boolean(string="Notification Email Queued", default=False, copy=False, readonly=True)
    status = fields.Selection(
        selection_add=[
            ("waiting_sap", "Process SAP"),
            ("process_sap", "Process SAP"),
            ('open_wo', 'Open - WO'),
        ],
        ondelete={
            'waiting_sap': 'cascade',
            'process_sap': 'cascade',
            'open_wo': 'cascade',
        },
    )
    pm_work_order_id = fields.Many2one(comodel_name='pm.work.order', string="Work Order", tracking=True)

    def _get_closed_write_allowed_fields(self):
        allowed_fields = super()._get_closed_write_allowed_fields()
        if self.env.su:
            allowed_fields |= {'notification_email_queued'}
        return allowed_fields

    @api.model
    def cron_queue_pm_notification_emails(self):
        template = self.env.ref('pm_work_order_tagging.mail_template_pm_notification_created')
        if not template:
            _logger.error("PM notification email template not found")
            return True

        records = self.sudo().with_context(active_test=False)
        last_id = 0
        while batch := records.search([
            ('id', '>', last_id),
            ('nomor_notifikasi', 'not in', (False, '')),
            ('notification_email_queued', '=', False),
        ], order='id', limit=100):
            last_id = batch[-1].id
            batch = batch.try_lock_for_update(allow_referencing=True)
            batch.invalidate_recordset([
                'nomor_notifikasi',
                'notification_email_queued',
            ])
            batch = batch.filtered(
                lambda record: (record.nomor_notifikasi or '').strip()
                and not record.notification_email_queued,
            )
            if not batch:
                continue

            departments = self.env['tagging.department'].sudo().search([
                ('active', '=', True),
                ('company_id', 'in', batch.company_id.ids),
                ('department_type', '=', 'planner'),
            ])
            pics = departments.mapped('pic_ids').filtered('active')
            pics |= self.env['tagging.pic'].sudo().search([
                ('active', '=', True),
                ('department_ids', 'in', departments.ids),
            ])
            recipients_by_company = {}
            for company in batch.company_id:
                company_departments = departments.filtered(lambda department: department.company_id == company)
                company_pics = pics.filtered(
                    lambda pic: pic.department_id in company_departments
                    or bool(pic.department_ids & company_departments),
                )
                emails = sorted(set(tools.email_normalize_all(
                    ','.join(company_pics.mapped('email')),
                )))
                if emails:
                    recipients_by_company[company.id] = ','.join(emails)

            queue_batch = batch.filtered(lambda record: record.company_id.id in recipients_by_company)
            missing_recipient_batch = batch - queue_batch
            if missing_recipient_batch:
                _logger.warning(
                    "PM notification email pending: planner recipient not found "
                    "for tagging IDs %s",
                    missing_recipient_batch.ids,
                )
            if not queue_batch:
                continue

            try:
                with self.env.cr.savepoint():
                    rendered = template.sudo()._generate_template(
                        queue_batch.ids,
                        (
                            'auto_delete',
                            'body_html',
                            'email_cc',
                            'email_from',
                            'mail_server_id',
                            'reply_to',
                            'scheduled_date',
                            'subject',
                        ),
                    )
                    mails = []
                    for record in queue_batch:
                        values = rendered[record.id]
                        values.update({
                            'auto_delete': False,
                            'body': values['body_html'],
                            'email_to': recipients_by_company[record.company_id.id],
                            'model': False,
                            'res_id': False,
                        })
                        if not values.get('email_from'):
                            values.pop('email_from', None)
                        mails.append(values)

                    created_mails = self.env['mail.mail'].sudo().create(mails)
                    if len(created_mails) != len(queue_batch):
                        raise ValidationError("Not all PM notification emails could be queued")
                    queue_batch.write({'notification_email_queued': True})
            except Exception:
                _logger.exception("Failed to queue PM notification emails for tagging IDs %s", batch.ids)
        return True

    def action_open_pm_notif_wizard(self):
        self.ensure_one()
        view = self.env.ref('pm_work_order_tagging.pm_notification_wizard_form_views')
        return {
            'type': 'ir.actions.act_window',
            'name': 'PM Notification Wizard',
            'res_model': 'pm.notification.wizard',
            'views': [(view.id, 'form')],
            'target': 'new',
            'context': {
                'default_tagging_id': self.id,
                'default_company_id': self.company_id.id,
            },
        }

    def action_set_create_work_order(self):
        for rec in self:
            if rec.status != 'validated':
                raise ValidationError("Work Order hanya bisa dibentuk saat status Validated!")
            if not rec.parent_equipment_id:
                raise ValidationError("Untuk membentuk WO harus mengisi Parent Equipment terlebih dahulu!")
            if not rec.equipment_id:
                raise ValidationError("Untuk membentuk WO harus mengisi Equipment terlebih dahulu!")

            rec.write({
                'close_start_date': False,
                'close_end_date': False,
                'close_description': False,
                'close_reason': False,
                'close_photo': False,
                'close_photo_filename': False,
            })
            rec.message_post(body="Close Evidence dikosongkan karena membuat Work Order saat Validated")
            rec.write({'status': 'waiting_sap'})
            # vals = {
            #     'tagging_id': rec.id,
            #     'company_id': rec.company_id.id if rec.company_id else False,
            #     'system_id': rec.system_id.id if rec.system_id else False,
            #     'sub_system_id': rec.sub_system_id.id if rec.sub_system_id else False,
            #     'equipment_id': rec.parent_equipment_id.id,
            #     'sub_equipment_id': rec.equipment_id.id,
            #     'state': 'draft',
            # }
            # wo = self.env['pm.work.order'].create(vals)
            # if wo:
            #     rec.write({
            #         'status': 'waiting_sap',
            #         'pm_work_order_id': wo.id,
            #     })
