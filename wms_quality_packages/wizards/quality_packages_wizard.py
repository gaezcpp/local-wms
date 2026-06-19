from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError


class QualityPackagesWizard(models.TransientModel):
    _name = 'quality.packages.wizard'
    _description = 'Quality Packages Wizard'
    
    quality_packages_id = fields.Many2one(comodel_name='quality.packages', string="AFT")
    category_aft_id = fields.Many2one(comodel_name='category.quality.packages', string="Category")
    other_reason = fields.Text(string="Other Reason")
    is_to_block = fields.Boolean(string="To Blocked", default=False)
    
    def action_aft_wizard(self):
        self.ensure_one()
        
        if not self.quality_packages_id:
            raise UserError("Data AFT Kosong, silahkan refresh halaman dan lakukan proses ulang!")
        
        is_other_reason = self.category_aft_id.name.strip().lower() == 'others'
        if is_other_reason and not self.other_reason:
            raise UserError("Reason (Other Reason) wajib diisi untuk melanjutkan proses!")
        
        if self.is_to_block:
            if not self.other_reason:
                raise UserError("Other Reason perlu diisi untuk melakukan proses Done untuk To Blocked!")
            
            self.quality_packages_id.write({
                'category_aft_id': self.category_aft_id.id,
                'other_reason': self.other_reason if is_other_reason else False,
            })
            return self.quality_packages_id.action_done()
        else:
            if not self.category_aft_id:
                raise UserError("Category Wajib diisi!")
            
            self.quality_packages_id.write({
                'category_aft_id': self.category_aft_id.id,
                'other_reason': self.other_reason if is_other_reason else False,
            })
            
            return self.quality_packages_id.action_reject()