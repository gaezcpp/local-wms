from odoo import models, fields, api
from odoo.exceptions import ValidationError

class PmAnalysis(models.Model):
    _name = 'pm.analysis'
    _description = 'Plan Maintenance WO Analysis'
    _rec_name = 'name'
    
    name = fields.Char(string="Name")
    code = fields.Char(string="Code")
    need_desc = fields.Boolean(string="Need Description?")
    active = fields.Boolean(string="Active", default=True)