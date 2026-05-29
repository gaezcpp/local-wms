from odoo import models, fields, api


class InheritStockPickingType(models.Model):
    _inherit = 'stock.picking.type'
    
    uu_only = fields.Boolean(string="UU Only", default=False)
    production_only = fields.Boolean(string="Production Only", default=False)
    move_type_sap = fields.Char(string="Move Type SAP")
    packaging_type_id = fields.Many2one(comodel_name='stock.picking.type', string="Packaging Type")
    checker_only = fields.Boolean(string="Checker Only", default=False)
    mandatory_destination = fields.Boolean(string="Mandatory Destination", default=False)