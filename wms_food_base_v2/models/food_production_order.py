from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class FoodProductionOrder(models.Model):
    _name = 'food.production.order'
    _description = 'Food Production Order'
    _rec_name = 'name'
    _order = 'id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    name = fields.Char(string="Name", default="New", required=True)
    order_type = fields.Char(string="Order Type")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('teco', 'TECO'),
    ], string="State", default='draft')
    start_date = fields.Date(string="Start Date")
    end_date = fields.Date(string="End Date")
    product_id = fields.Many2one(comodel_name='product.template', string="SKU")
    uom_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    order_qty = fields.Float(string="Order Qty")
    gr_qty = fields.Float(string="GR Qty")
    remaining_qty = fields.Float(string="Remaining Qty")
    company_id = fields.Many2one(comodel_name='res.company', string="Company", default=lambda self:self.env.company)
    