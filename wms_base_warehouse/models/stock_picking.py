from odoo import models, fields, api


class InheritBaseStockPicking(models.Model):
    _inherit = 'stock.picking'
    
    production_shift_id = fields.Many2one(comodel_name='production.shift', string="Shift", tracking=True)