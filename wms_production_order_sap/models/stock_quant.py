from odoo import models, fields, api



class StockQuant(models.Model):
    _inherit = 'stock.quant'
    
    po_sap_id = fields.Many2one(comodel_name='production.order.sap', string="Prod Order")