from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
_logger  = logging.getLogger(__name__)

class QualityPackages(models.Model):
    _name = 'quality.packages'
    _description = 'Quality Packages'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    name = fields.Char(string="Name", default="New")
    picking_id = fields.Many2one(comodel_name='stock.picking', string="Picking", tracking=True)
    packages_ids = fields.Many2many(comodel_name='stock.package', string="Packages", tracking=True)
    company_id = fields.Many2one(comodel_name='res.company', string="Company", default=lambda self: self.env.company)
    notes = fields.Text(string="Notes", tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
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
    
    def action_completed(self):
        for rec in self:
            if rec.state == 'draft':
                if not rec.notes:
                    raise ValidationError("Notes tidak boleh kosong!")
                if not rec.picking_id or len(rec.packages_ids) < 1:
                    raise ValidationError("Picking atau Packages haris diisi!")
                
                rec.state = 'completed'
            else:
                raise ValidationError(f"Tidak bisa update status menjadi completed karena {rec.name} tidak dalam state draft!")
    
    def action_failed(self):
        for rec in self:
            if rec.state == 'draft':
                if not rec.notes:
                    raise ValidationError("Notes tidak boleh kosong!")
                if not rec.picking_id or len(rec.packages_ids) < 1:
                    raise ValidationError("Picking atau Packages haris diisi!")
                
                rec.state = 'failed'
            else:
                raise ValidationError(f"Tidak bisa update status menjadi Failed karena {rec.name} tidak dalam state draft!")