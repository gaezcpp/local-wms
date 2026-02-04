from odoo import models, fields, api


class ProductionShiftCustom(models.Model):
    _name = 'production.shift'
    _description = 'Production Shift'
    _rec_name = 'name'
    
    active = fields.Boolean(string="Active", default=True)
    name = fields.Char(string="Name")
    company_ids = fields.Many2many(comodel_name='res.company', string="Company")