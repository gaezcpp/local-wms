from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ProductionCode(models.Model):
    _name = 'production.code'
    _description = 'Production Code'
    _rec_name = 'company_id'
    
    company_id = fields.Many2one(comodel_name='res.company', string="Company", required=True)
    code = fields.Text(string="Code")