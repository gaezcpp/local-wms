from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ProductionChronosLine(models.Model):
    _name = 'production.chronos.line'
    _description = 'Production Chronos Line'
    
    po_chronos_id = fields.Many2one(comodel_name='production.chronos', string="PO Chronos")
    picking_id = fields.Many2one(comodel_name='stock.picking', string="Nomor")
    warehouse_id = fields.Many2one(comodel_name='stock.warehouse', string="Warehouse")
    product_id = fields.Many2one(comodel_name='product.product', string="Product")
    quantity = fields.Float(string="Quantity")
    product_uom_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    pack_qty = fields.Float(string="Pack Qty")
    product_pack_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    counter_awal = fields.Float(string="Counter Awal")
    counter_akhir = fields.Float(string="Counter Akhir")