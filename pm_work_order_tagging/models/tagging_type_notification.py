from odoo import models, fields, api


class TaggingTypeNotification(models.Model):
    _name = 'tagging.type.notification'
    _description = 'Tagging Type Notification'
    _rec_name = 'name'
    
    name = fields.Char(string="Name")
    desc = fields.Text(string="Description")
    company_id = fields.Many2one(comodel_name='res.company', string="Company")
    