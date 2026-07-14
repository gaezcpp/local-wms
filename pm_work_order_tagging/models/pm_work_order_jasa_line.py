from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PMWorkOrderJasaLine(models.Model):
    _name = 'pm.work.order.jasa.line'
    _description = 'PM WO Jasa Line'
    
    pm_work_order_id = fields.Many2one(comodel_name='pm.work.order')
    no_service = fields.Char(string='No Service')
    description = fields.Char(string="Description")
    bwart = fields.Char(string="Status")