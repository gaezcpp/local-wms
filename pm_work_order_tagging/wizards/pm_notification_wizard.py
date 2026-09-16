from odoo import models, fields, api
from odoo.exceptions import ValidationError


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
            raise ValidationError("Tagging tidak ditemukan, silahkan refresh dan ulangi proses!")
        if not self.tagging_type_notification_id:
            raise ValidationError("Notification Type harus diisi untuk melanjutkan proses!")
        if not self.notification_desc:
            raise ValidationError("Notification Desc harus diisi untuk melanjutkan proses!")
        self.tagging_id.write({
            'tagging_type_notification_id': self.tagging_type_notification_id.id,
            'notification_desc': self.notification_desc,
        })
        self.tagging_id.action_set_create_work_order()