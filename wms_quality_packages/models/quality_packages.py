from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
_logger  = logging.getLogger(__name__)

class QualityPackages(models.Model):
    _name = 'quality.packages'
    _description = 'Quality Packages'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    
    name = fields.Char(string="Name", default="New")
    picking_id = fields.Many2one(comodel_name='stock.picking', string="Picking", tracking=True)
    packages_ids = fields.Many2many(comodel_name='stock.package', string="Packages")
    company_id = fields.Many2one(comodel_name='res.company', string="Company", default=lambda self: self.env.company)
    notes = fields.Text(string="Notes", tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ], string="State", default="draft", tracking=True)
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('quality.packages') or _('New')
        return super().create(vals_list)
    
    @api.onchange('picking_id')
    def _onchange_picking_packages(self):
        for rec in self:
            if rec.picking_id:
                packages = rec.picking_id.move_ids.mapped('package_ids').ids
                rec.packages_ids = [(6, 0, packages)]
            else:
                rec.packages_ids = [(5, 0, 0)]

    def action_open_wizard_packages(self):
        self.ensure_one()
        view = self.env.ref('wms_quality_packages.package_wizards_form_views')

        wizard = self.env['package.wizards'].create({'quality_package_id': self.id})

        line_vals = []
        for pack in self.packages_ids:
            line_vals.append({
                'package_wizard_id': wizard.id,
                'package_id': pack.id,
                'parent_package_id': pack.parent_package_id.id,
                'package_type_id': pack.package_type_id.id,
                'location_id': pack.location_id.id,
                'pack_date': pack.pack_date,
                'pallet_status': pack.pallet_status,
                'state': pack.state,
            })

        self.env['package.wizards.line'].create(line_vals)

        return {
            'name': 'Packages Wizards',
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'package.wizards',
            'views': [(view.id, 'form')],
            'res_id': wizard.id,
            'target': 'new',
        }

    def action_draft(self):
        for rec in self:
            if rec.state != 'draft':
                rec.state = 'draft'
    
    def action_in_progress(self):
        for rec in self:
            if rec.state == 'draft':
                rec.state = 'in_progress'
            else:
                raise ValidationError(f"Tidak bisa update status menjadi in_progress karena {rec.name} tidak dalam state draft!")
                
    def action_failed(self):
        for rec in self:
            if rec.state == 'in_progress':
                if not rec.notes:
                    raise ValidationError("Notes tidak boleh kosong!")
                
                rec.state = 'failed'
            else:
                raise ValidationError(f"Tidak bisa update status menjadi Failed karena {rec.name} tidak dalam state draft!")