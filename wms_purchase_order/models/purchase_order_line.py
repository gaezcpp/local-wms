from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'
    
    sap_sequence = fields.Integer(string="SAP Seq")
    order_seq = fields.Integer(string="Order Seq")
    
    def _prepare_stock_moves(self, picking):
        res = super(PurchaseOrderLine, self)._prepare_stock_moves(picking)
        for vals in res:
            po_line_id = vals.get('purchase_line_id')
            if po_line_id:
                po_line = self.browse(po_line_id)
                vals['sap_seq'] = po_line.sap_sequence
                vals['order_seq'] = po_line.order_seq
                
        return res