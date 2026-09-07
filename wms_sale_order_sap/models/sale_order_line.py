from odoo import models, fields, api


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'
    
    sap_sequence = fields.Integer(string="SAP Seq")
    order_seq = fields.Integer(string="Order Seq")
    order_selection = fields.Selection([
        ('order', 'Order'),
        ('gratis', 'Gratis'),
    ], string="Order Selection", default='order')
    rumus_gratis = fields.Integer(string="Rumus Gratis", default=0, help="quantity product order / product gratis + 1, contoh order 200 gratis 8 jadi 25+1 = 26")

    # prepare stock.move
    def _prepare_procurement_values(self):
        values = super(SaleOrderLine, self)._prepare_procurement_values()
        values.update({
            'sap_sequence': self.sap_sequence,
            'order_seq': self.order_seq,
            'order_selection': self.order_selection,
        })
        return values