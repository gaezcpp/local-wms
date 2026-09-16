from odoo import models, fields, api


class ProductionShiftCustom(models.Model):
    _name = 'food.production.shift'
    _description = 'Food Production Shift'
    _rec_name = 'name'
    
    active = fields.Boolean(string="Active", default=True)
    name = fields.Char(string="Name")
    code = fields.Char(string="Code", index=True)
    date_start = fields.Char(string="Date Start", index=True)
    date_end = fields.Char(string="Date End", index=True)
    company_id = fields.Many2one(comodel_name='res.company', string="Company", default=lambda self: self.env.company)