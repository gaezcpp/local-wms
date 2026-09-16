from odoo import models, fields, api


class FoodInheritStockPickingType(models.Model):
    _inherit = 'stock.picking.type'
    
    need_txhistorytemp = fields.Boolean(string="Need Tx History Temp", default=False)
    checker_in = fields.Boolean(string="Checker In", default=False)
    checker_out = fields.Boolean(string="Checker Out", default=False)
    hide_edit_barcode = fields.Boolean(string="Hide Edit Barcode", default=False)
    hide_zero_qty = fields.Boolean(string="Hide Zero Qty", default=False)
    restrict_over_demand = fields.Boolean(string="Restrict Over Demand", default=False)
    split_pallet = fields.Boolean(string="Split Pallet", default=False)