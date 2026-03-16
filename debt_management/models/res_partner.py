from odoo import models, fields, api, _


class InheritResPartner(models.Model):
    _inherit = 'res.partner'
    
    
    has_debt = fields.Boolean(string="Has Debt?", default=False, tracking=True)