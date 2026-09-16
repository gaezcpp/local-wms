from odoo import models, fields, api

class ProductionGroup(models.Model):
    _name = 'food.production.group'
    _description = 'Production Group'
    _rec_name = 'name'
    
    name = fields.Char(string="Name")
    code = fields.Char(string="Code", index=True)
    company_id = fields.Many2one(comodel_name='res.company', string="Company")