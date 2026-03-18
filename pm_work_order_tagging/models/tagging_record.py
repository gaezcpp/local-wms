from odoo import models, fields, api
from odoo.exceptions import ValidationError


class InheritTaggingRecord(models.Model):
    _inherit = 'tagging.record'
    
    tagging_type_notification_id = fields.Many2one(comodel_name='tagging.type.notification', string="Notification Type", tracking=True)
    notification_desc = fields.Text(string="Notification Desc", tracking=True)
    
    @api.onchange('tagging_type_notification_id')
    def _onchange_tagging_notif(self):
        for rec in self:
            if rec.tagging_type_notification_id:
                rec.notification_desc = rec.tagging_type_notification_id.desc
            else:
                rec.notification_desc = False
    
    def action_set_create_work_order(self):
        for rec in self:
            if rec.status == 'validated':
                if not rec.parent_equipment_id:
                    raise ValidationError("Untuk membentuk WO harus mengisi Parent Equipment terlebih dahulu!")
                if not rec.equipment_id:
                    raise ValidationError("Untuk membentuk WO harus mengisi Equipment terlebih dahulu!")
                
                company = self.env['res.company'].sudo().search([('company_registry', '=', rec.plant_code)], limit=1)
                vals = {
                    'tagging_id': rec.id,
                    'company_id': company.id if company else False,
                    'system_id': rec.system_id.id if rec.system_id else False,
                    'sub_system_id': rec.sub_system_id.id if rec.sub_system_id else False,
                    'equipment_id': rec.parent_equipment_id.id,
                    'sub_equipment_id': rec.equipment_id.id,
                    'state': 'draft',
                }
                self.env['pm.work.order'].create(vals)
                rec.status = 'open_wo'
            else:
                raise ValidationError("Work Order hanya bisa dibentuk saat status Validated!")