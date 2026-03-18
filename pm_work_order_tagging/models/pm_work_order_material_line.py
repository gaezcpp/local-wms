from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PMWorkOrderMaterialLine(models.Model):
    _name = 'pm.work.order.material.line'
    _description = 'PM WO Material Line'
    
    pm_work_order_id = fields.Many2one(comodel_name='pm.work.order')
    sequence = fields.Integer(string="Sequence")
    product_sparepart_id = fields.Many2one(comodel_name='tagging.spare_part', string="Material")
    product_material = fields.Char(string='SKU')
    quantity = fields.Float(string="Quantity")