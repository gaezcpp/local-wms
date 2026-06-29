from odoo import models, fields, api


class InheritLotPOSAP(models.Model):
    _inherit = 'stock.lot'
    
    po_sap_id = fields.Many2one(comodel_name='production.order.sap', string="PO SAP", tracking=True)