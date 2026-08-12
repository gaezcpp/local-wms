from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class InhStockPackage(models.Model):
    _name = 'stock.package'
    _inherit = ['stock.package', 'mail.thread', 'mail.activity.mixin']
    
    yellow_tag = fields.Selection([
        ('ready', 'Ready'),
        ('hold', 'Hold'),
    ], string="Yellow Tag", default='ready', tracking=True)
    
    def action_ready(self):
        for rec in self:
            if rec.yellow_tag != 'ready':
                rec.yellow_tag = 'ready'
                
    def action_hold(self):
        for rec in self:
            if rec.yellow_tag != 'hold':
                rec.yellow_tag = 'hold'