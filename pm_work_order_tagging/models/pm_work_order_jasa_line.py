from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PMWorkOrderJasaLine(models.Model):
    _name = 'pm.work.order.jasa.line'
    _description = 'PM WO Jasa Line'
    
    pm_work_order_id = fields.Many2one(comodel_name='pm.work.order')
    material_desc = fields.Char(string="Material")
    sku_desc = fields.Char(string="SKU")
    quantity = fields.Float(string="Quantity")
    gr_doc = fields.Char(string="GR Doc")
    is_gr = fields.Boolean(string="GR", default=False)