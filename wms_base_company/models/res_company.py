from odoo import models, fields, api


class InheritResCompany(models.Model):
    _inherit = 'res.company'
    
    sync_wms = fields.Boolean(string="Sync WMS", default=False)
    sync_pm = fields.Boolean(string="Sync PM", default=False)