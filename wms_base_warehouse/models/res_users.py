from odoo import models, fields, api


class InheritBaseUsers(models.Model):
    _inherit = 'res.users'
    
    # NOTE Pindah pake WAREHOUSE ACCESS CONTROL
    picking_type_ids = fields.Many2many(comodel_name='stock.picking.type', string="Operation Types")