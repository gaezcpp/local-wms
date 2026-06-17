from odoo import models, fields, api
from odoo.exceptions import ValidationError


# class CronLogging(models.Model):
#     _name = 'cron.logging'
#     _description = 'Cron Logging'
#     _rec_name = 'name'
    
#     name = fields.Char(string="Name")
#     cron_id = fields.Many2one(comodel_name='ir.cron', string="Cron")
#     model_id = fields.Many2one(comodel_name='ir.model', string="Model")
#     messages = fields.Text(string="Messages")