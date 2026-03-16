from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class PlanMaintenanceWorkOrder(models.Model):
    _name = 'pm.work.order'
    _description = 'PM Work Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    
    name = fields.Char(string="Name", default="New")
    tagging_id = fields.Many2one(comodel_name='tagging.record', string="Tagging", tracking=True)
    type_mo = fields.Char(string="Type MO", tracking=True)
    company_id = fields.Many2one(comodel_name='res.company', string="Company", tracking=True)
    system_id = fields.Many2one(comodel_name='tagging.system', string="System", tracking=True)
    sub_system_id = fields.Many2one(comodel_name='tagging.subsystem', string="Sub System", tracking=True)
    equipment_id = fields.Many2one(comodel_name='maintenance.equipment', string="Equipment", domain=[('parent_equipment_id', '=', False)], tracking=True)
    sub_equipment_id = fields.Many2one(comodel_name='maintenance.equipment', string="Sub Equipment", domain=[('parent_equipment_id', '!=', False)], tracking=True)
    pm_wo_material_line_ids = fields.One2many('pm.work.order.material.line', 'pm_work_order_id')
    maintenance_type = fields.Selection([
        ('CORRECTIVE', 'CORRECTIVE'),
        ('PREVENTIF', 'PREVENTIF'),
    ], string="Maintenance Type", default=False, tracking=True)
    priority = fields.Char(string="Priority", tracking=True)
    date_from = fields.Datetime(string="Date From", tracking=True)
    date_to = fields.Datetime(string="Date To", tracking=True)
    analysis = fields.Text(string="Analysis", tracking=True)
    problem_handling = fields.Text(string="Problem Handling", tracking=True)
    photo_attachment = fields.Binary(string="Photo", tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('closed', 'Closed'),
        ('rejected', 'Rejected'),
    ], string="State", default='draft')
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('pm.work.order') or _('New')
        return super().create(vals_list)
    
    def action_close(self):
        for rec in self:
            if rec.state == 'draft' and not rec.type_mo:
                if rec.date_from:
                    raise ValidationError("Tidak bisa melakukan pengisian Date From jika status selain draft dan Type MO belum terisi!")
                if rec.date_to:
                    raise ValidationError("Tidak bisa melakukan pengisian Date To jika status selain draft dan Type MO belum terisi!")
                if rec.analysis:
                    raise ValidationError("Tidak bisa melakukan pengisian Analysis jika status selain draft dan Type MO belum terisi!")
                if rec.problem_handling:
                    raise ValidationError("Tidak bisa melakukan pengisian Problem Handling jika status selain draft dan Type MO belum terisi!")
                if rec.photo_attachment:
                    raise ValidationError("Tidak bisa melakukan pengisian Photo jika status selain draft dan Type MO belum terisi!")
                
                rec.state = 'closed'
    
    # @api.onchange('date_from', 'date_to', 'analysis', 'problem_handling', 'photo_attachment')
    # def _onchange_close_evidence(self):
    #     for rec in self:
    #         if rec.state == 'draft' and not rec.type_mo:
    #             if rec.date_from:
    #                 raise ValidationError("Tidak bisa melakukan pengisian Date From jika status selain draft dan Type MO belum terisi!")
    #             if rec.date_to:
    #                 raise ValidationError("Tidak bisa melakukan pengisian Date To jika status selain draft dan Type MO belum terisi!")
    #             if rec.analysis:
    #                 raise ValidationError("Tidak bisa melakukan pengisian Analysis jika status selain draft dan Type MO belum terisi!")
    #             if rec.problem_handling:
    #                 raise ValidationError("Tidak bisa melakukan pengisian Problem Handling jika status selain draft dan Type MO belum terisi!")
    #             if rec.photo_attachment:
    #                 raise ValidationError("Tidak bisa melakukan pengisian Photo jika status selain draft dan Type MO belum terisi!")