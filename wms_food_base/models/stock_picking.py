from odoo import models, fields, api


class FoodStockPicking(models.Model):
    _inherit = 'stock.picking'