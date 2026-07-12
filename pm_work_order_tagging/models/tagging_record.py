from odoo import models, fields, api
from odoo.exceptions import ValidationError


class InheritTaggingRecord(models.Model):
    _inherit = 'tagging.record'
    
    tagging_type_notification_id = fields.Many2one(comodel_name='tagging.type.notification', string="Notification Type", tracking=True)
    notification_desc = fields.Text(string="Notification Desc", tracking=True)
    nomor_notifikasi = fields.Text(string="Nomor Notifikasi", tracking=True)
    status = fields.Selection(
        selection_add=[
            ("waiting_sap", "Waiting SAP"),
            ("process_sap", "Process SAP"),
            ('open_wo', 'Open - WO')
        ], 
        ondelete={
            'waiting_sap': 'cascade',
            'process_sap': 'cascade',
            'open_wo': 'cascade'
        }
    )
    pm_work_order_id = fields.Many2one(comodel_name='pm.work.order', string="Work Order", tracking=True)
    
    @api.onchange('tagging_type_notification_id')
    def _onchange_tagging_notif(self):
        for rec in self:
            if rec.tagging_type_notification_id:
                rec.notification_desc = rec.tagging_type_notification_id.desc
            else:
                rec.notification_desc = False
    
    def action_set_create_work_order(self):
        for rec in self:
            if rec.status != 'validated':
                raise ValidationError("Work Order hanya bisa dibentuk saat status Validated!")
            if not rec.parent_equipment_id:
                raise ValidationError("Untuk membentuk WO harus mengisi Parent Equipment terlebih dahulu!")
            if not rec.equipment_id:
                raise ValidationError("Untuk membentuk WO harus mengisi Equipment terlebih dahulu!")
            if not rec.tagging_type_notification_id:
                raise ValidationError("Notification Type harus diisi untuk melanjutkan proses!")
            if not rec.notification_desc:
                raise ValidationError("Notification Desc harus diisi untuk melanjutkan proses!")
            
            rec.write({
                'close_start_date': False,
                'close_end_date': False,
                'close_description': False,
                'close_reason': False,
                'close_photo': False,
                'close_photo_filename': False
            })
            rec.message_post(body="Close Evidence dikosongkan karena membuat Work Order saat Validated")
            
            vals = {
                'tagging_id': rec.id,
                'company_id': rec.company_id.id if rec.company_id else False,
                'system_id': rec.system_id.id if rec.system_id else False,
                'sub_system_id': rec.sub_system_id.id if rec.sub_system_id else False,
                'equipment_id': rec.parent_equipment_id.id,
                'sub_equipment_id': rec.equipment_id.id,
                'state': 'draft',
            }
            wo = self.env['pm.work.order'].create(vals)
            if wo:
                rec.write({
                    'status': 'waiting_sap',
                    'pm_work_order_id': wo.id,
                })