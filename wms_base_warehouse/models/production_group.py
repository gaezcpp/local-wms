from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ProductionGroup(models.Model):
    _name = 'production.group'
    _description = 'Production Group'
    _rec_name = 'name'
    
    name = fields.Char(string="Name")
    code = fields.Char(string="Code", index=True)
    user_id = fields.Many2one(comodel_name='res.users', string="User", index=True)
    company_id = fields.Many2one(comodel_name='res.company', string="Company")