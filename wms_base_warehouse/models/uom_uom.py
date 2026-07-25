from odoo import models, fields, api


class InheritUomUom(models.Model):
    _inherit = 'uom.uom'

    sap_synchronize = fields.Boolean(string="SAP Synchronize", default=False)
    sap_name = fields.Char(string="SAP Name")

    def _get_fields_stock_barcode(self):
        res = super()._get_fields_stock_barcode()
        if 'sap_name' not in res:
            res.append('sap_name')
        return res