from odoo import models, fields, api


class InheritUomUom(models.Model):
    _inherit = 'uom.uom'

    sap_sync = fields.Boolean(string="SAP Sync", default=False)
    sap_name = fields.Char(string="SAP Name")

    def _get_fields_stock_barcode(self):
        res = super()._get_fields_stock_barcode()
        if 'sap_name' not in res:
            res.append('sap_name')
        return res