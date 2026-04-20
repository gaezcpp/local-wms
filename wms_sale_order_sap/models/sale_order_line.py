from odoo import models, fields, api


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'
    
    sap_sequence = fields.Integer(string="SAP Seq")
    sap_po_sequence = fields.Integer(string="Order Seq")
    
    # prepare stock.move
    def _prepare_procurement_values(self):
        values = super(SaleOrderLine, self)._prepare_procurement_values()
        values.update({'sap_sequence': self.sap_sequence,})
        return values