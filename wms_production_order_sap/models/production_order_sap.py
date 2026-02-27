from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ProductionOrderSAP(models.Model):
    _name = 'production.order.sap'
    _description = 'Production Order SAP'
    _rec_name = 'po_number'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    po_number = fields.Char(string="Production Order")
    order_type = fields.Char(string="Order Type")
    start_date = fields.Date(string="Start Date")
    finish_date = fields.Date(string="Finish Date")
    product_id = fields.Many2one(comodel_name='product.template', string="Product")
    order_qty = fields.Float(string="Order Qty")
    company_registry = fields.Char(string="Company Registry")
    company_id = fields.Many2one(comodel_name='res.company', string="Company", default=lambda self: self.env.company)
    state = fields.Selection([
        ('open', 'Open'),
        ('teko', 'TEKO'),
        ('closed', 'Closed'),
    ], string="Status", default='open')
    sap_pp = fields.Boolean(string="SAP PP", default=False)