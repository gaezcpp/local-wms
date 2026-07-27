from odoo import models, fields, api


class ProductionShiftCustom(models.Model):
    _name = 'production.shift'
    _description = 'Production Shift'
    _rec_name = 'name'
    
    active = fields.Boolean(string="Active", default=True)
    name = fields.Char(string="Name")
    code = fields.Char(string="Code", index=True)
    date_start = fields.Char(string="Date Start", index=True)
    date_end = fields.Char(string="Date End", index=True)
    company_ids = fields.Many2many(comodel_name='res.company', string="Companies")
    company_id = fields.Many2one(comodel_name='res.company', string="Companoe")