from odoo import models, fields, api


class InhResCompany(models.Model):
    _inherit = 'res.company'
    
    wms_type = fields.Selection([
        ('FOOD', 'FOOD'),
        ('FEED', 'FEED'),
    ], string="WMS Type", default=False)