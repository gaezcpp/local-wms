import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class PmNotificationWizard(models.TransientModel):
    _name = 'pm.notification.wizard'
    _description = 'PM Notification Wizard'

    tagging_id = fields.Many2one(comodel_name='tagging.record', string="Tagging")
    company_id = fields.Many2one(comodel_name='res.company', string="Company")
    tagging_type_notification_id = fields.Many2one(comodel_name='tagging.type.notification', string="Notification Type")
    notification_desc = fields.Text(string="Notification Desc")

    @api.onchange('tagging_type_notification_id')
    def _onchange_tagging_notif(self):
        for rec in self:
            if rec.tagging_type_notification_id:
                rec.notification_desc = rec.tagging_type_notification_id.desc
            else:
                rec.notification_desc = False

    def action_confirm(self):
        self.ensure_one()
        if not self.tagging_id:
            message = "Tagging tidak ditemukan, silahkan refresh dan ulangi proses!"
            raise ValidationError(message)
        if not self.tagging_type_notification_id:
            message = "Notification Type harus diisi untuk melanjutkan proses!"
            raise ValidationError(message)
        if not self.notification_desc:
            message = "Notification Desc harus diisi untuk melanjutkan proses!"
            raise ValidationError(message)
        if self.company_id != self.tagging_id.company_id:
            message = "Company wizard harus sama dengan company tagging!"
            raise ValidationError(message)
        if self.tagging_type_notification_id.company_id != self.tagging_id.company_id:
            message = "Company Notification Type harus sama dengan company tagging!"
            raise ValidationError(message)
        email_to = self.env['ir.config_parameter'].sudo().get_param(
            'notification_tagging_email_to',
        )
        email_to = (email_to or '').strip()
        if not email_to:
            message = "Parameter notification_tagging_email_to belum disetting!"
            raise ValidationError(message)
        self.tagging_id.write({
            'tagging_type_notification_id': self.tagging_type_notification_id.id,
            'notification_desc': self.notification_desc,
        })
        self.tagging_id.action_set_create_work_order()
        template = self.env.ref('pm_work_order_tagging.mail_template_pm_notification_created')
        if not template:
            message = "PM notification email template tidak ditemukan!"
            raise ValidationError(message)
        try:
            with self.env.cr.savepoint():
                template.sudo().send_mail(
                    self.tagging_id.id,
                    email_values={
                        'email_to': email_to,
                        'model': False,
                        'res_id': False,
                    },
                )
        except Exception:
            _logger.exception("Failed to queue PM notification email for %s", self.tagging_id.name)
            message = "Email PM Notification gagal dibuat. Silakan ulangi proses!"
            raise ValidationError(message) from None
