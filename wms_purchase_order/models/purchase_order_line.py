from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'
    
    sap_sequence = fields.Integer(string="SAP Seq")