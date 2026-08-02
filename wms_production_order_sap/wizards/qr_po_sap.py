from odoo import models, fields, api
from odoo.exceptions import ValidationError


class QrPoSap(models.TransientModel):
    _name = 'qr.po.sap'
    _description = 'QR PO SAP Line'
    
    po_sap_id = fields.Many2one(comodel_name='production.order.sap', string="PO SAP")
    production_line_id = fields.Many2one(comodel_name='production.line', string="Production Line")
    
    def action_print_qr_line(self):
        self.ensure_one()
        if not self.po_sap_id or not self.production_line_id:
            raise ValidationError("Data tidak lengkap silahkan refresh halaman!")
        return self.env.ref('wms_production_order_sap.action_report_qr_po_sap_line').report_action(self)
