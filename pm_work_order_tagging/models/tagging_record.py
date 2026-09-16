from odoo import models, fields, api
from odoo.exceptions import ValidationError


class InheritTaggingRecord(models.Model):
    _inherit = 'tagging.record'
    
    tagging_type_notification_id = fields.Many2one(comodel_name='tagging.type.notification', string="Notification Type", tracking=True)
    notification_desc = fields.Text(string="Notification Desc", tracking=True)
    nomor_notifikasi = fields.Text(string="Nomor Notifikasi", tracking=True)
    status = fields.Selection(
        selection_add=[
            ("waiting_sap", "Process SAP"),
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
            }
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
                'close_photo_filename': False
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