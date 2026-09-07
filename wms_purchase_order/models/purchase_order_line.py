from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'
    
    sap_sequence = fields.Integer(string="SAP Seq")
    order_seq = fields.Integer(string="Order Seq")
    order_selection = fields.Selection([
        ('order', 'Order'),
        ('gratis', 'Gratis'),
    ], string="Order Selection", default='order')
    rumus_gratis = fields.Integer(string="Rumus Gratis", default=0, help="quantity product order / product gratis + 1, contoh order 200 gratis 8 jadi 25+1 = 26")
    
    def _prepare_stock_moves(self, picking):
        res = super(PurchaseOrderLine, self)._prepare_stock_moves(picking)
        for vals in res:
            po_line_id = vals.get('purchase_line_id')
            if po_line_id:
                po_line = self.browse(po_line_id)
                vals['sap_seq'] = po_line.sap_sequence
                vals['order_seq'] = po_line.order_seq
                vals['order_selection'] = po_line.order_selection
                
        return res