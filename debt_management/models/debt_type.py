from odoo import models, fields, api, _


class DebtType(models.Model):
    _name = 'debt.type'
    _description = 'Debt Type'
    _rec_name = 'name'
    
    name = fields.Char(string="Name")