from odoo import models, fields, api
from odoo.exceptions import ValidationError


class SapAft(models.Model):
    _name = 'sap.aft'
    _description = 'SAP AFT'
    _rec_name = 'name'
    
    name = fields.Char(string="Name")
    stock_type_from = fields.Selection([
        ('QI', 'QI'),
        ('BLOCKED', 'BLOCKED'),
        ('UU', 'UU'),
    ], string="Stock Type From", default='QI')
    stock_type_to = fields.Selection([
        ('QI', 'QI'),
        ('BLOCKED', 'BLOCKED'),
        ('UU', 'UU'),
    ], string="Stock Type To", default='QI')
    move_type = fields.Char(string="Move Type")