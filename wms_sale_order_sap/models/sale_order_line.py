from odoo import models, fields, api


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'
    
    sap_sequence = fields.Integer(string="SAP Seq")