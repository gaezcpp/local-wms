from odoo import models, fields, api
from odoo.exceptions import ValidationError


class DebtCustomer(models.Model):
    _name = 'debt.customer'
    _description = 'Debt Customer'
    _rec_name = 'name'
    _order = 'id desc'
    
    
    name = fields.Char(string="Name", required=True)
    