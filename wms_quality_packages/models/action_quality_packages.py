from odoo import models, fields, api


class ActionQualityPackages(models.Model):
    _name = 'action.quality.packages'
    _description = 'Action AFT'
    _rec_name = 'name'
    
    name = fields.Char(string="Name")