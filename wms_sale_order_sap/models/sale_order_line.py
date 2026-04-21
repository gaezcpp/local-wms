from odoo import models, fields, api


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'
    
    sap_sequence = fields.Integer(string="SAP Seq")
    order_seq = fields.Integer(string="Order Seq")
    
    # prepare stock.move
    def _prepare_procurement_values(self):
        values = super(SaleOrderLine, self)._prepare_procurement_values()
        values.update({
            'sap_sequence': self.sap_sequence,
            'order_seq': self.order_seq,
        })
        return values