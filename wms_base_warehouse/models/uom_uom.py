from odoo import models, fields, api


class InheritUomUom(models.Model):
    _inherit = 'uom.uom'
    
    sap_synchronize = fields.Boolean(string="SAP Synchronize", default=False, tracking=True)