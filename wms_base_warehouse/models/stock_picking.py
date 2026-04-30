from odoo import models, fields, api


class InheritBaseStockPicking(models.Model):
    _inherit = 'stock.picking'
    
    over_delivery = fields.Boolean(string="Over Delivery", tracking=True)
    production_shift_id = fields.Many2one(comodel_name='production.shift', string="Shift", tracking=True)
    production_order_name = fields.Char(string="Production Order", tracking=True)
    product_packaging_ids = fields.One2many('picking.packaging.line', 'picking_id')
    synchronize_sap = fields.Boolean(string="Synchronize SAP", default=False, tracking=True)
    production_only = fields.Boolean(related='picking_type_id.production_only', store=True, readonly=True)
    sloc_to = fields.Char(string="SLOC To")
    
    def _create_backorder(self, backorder_moves=None):
        backorders = super()._create_backorder(backorder_moves=backorder_moves)
        backorders.write({'synchronize_sap': False})
        return backorders
    
    def copy(self, default=None):
        default = dict(default or {})
        default['synchronize_sap'] = False
        return super().copy(default)