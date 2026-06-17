from odoo import models, fields, api


class StockWarehouseCategory(models.Model):
    _name = 'stock.warehouse.category'
    _description = 'Stock Warehouse Category'
    _rec_name = 'name'
    _order = 'id desc'
    
    name = fields.Char(string="Name")