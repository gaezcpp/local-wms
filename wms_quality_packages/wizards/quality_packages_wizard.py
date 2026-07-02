from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError


class QualityPackagesWizard(models.TransientModel):
    _name = 'quality.packages.wizard'
    _description = 'Quality Packages Wizard'
    
    quality_packages_id = fields.Many2one(comodel_name='quality.packages', string="AFT")
    category_aft_id = fields.Many2one(comodel_name='category.quality.packages', string="Category")
    block_action_id = fields.Many2one(comodel_name='action.quality.packages', string="Block Action")
    other_reason = fields.Text(string="Other Reason")
    is_to_block = fields.Boolean(string="To Blocked", default=False)
    
    def action_aft_wizard(self):
        self.ensure_one()
        
        if not self.quality_packages_id:
            raise UserError("Data AFT Kosong, silahkan refresh halaman dan lakukan proses ulang!")
        
        if not self.category_aft_id:
            raise ValidationError("Category AFT wajib diisi untuk melanjutkan proses")
        if not self.block_action_id:
            raise ValidationError("Block Action wajib diisi untuk melanjutkan proses")
            
        else:
            is_other_reason = self.category_aft_id.name.strip().lower() == 'others'
            if is_other_reason and not self.other_reason:
                raise ValidationError("Other Reason wajib diisi karena Category Other!")
        
            self.quality_packages_id.write({
                'category_aft_id': self.category_aft_id.id,
                'block_action_id': self.block_action_id.id,
                'other_reason': self.other_reason,
            })
            
        if self.is_to_block:
            return self.quality_packages_id.action_done()
        else:
            return self.quality_packages_id.action_reject()