from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class MasterQR(models.Model):
    _name = 'food.master.qr'
    _description = 'Food Master QR'
    _rec_name = 'name'
    
    name = fields.Char(string="Barcode")
    client_no = fields.Char(string="Client No")
    product_id = fields.Many2one(comodel_name='product.template', string="Product")
    company_id = fields.Many2one(comodel_name='res.company', string="Company", default=lambda self: self.env.company)
    prod_code = fields.Char(string="Production Code")
    prod_order_no = fields.Char(string="Production Order No.")
    prod_date = fields.Date(string="Production Date")
    prod_group = fields.Char(string="Production Group")
    harvest_date = fields.Date(string="Harvest Date")
    mat_group = fields.Char(string="Mat Group")
    pack_date = fields.Datetime(string="Pack Time")
    pack_group = fields.Char(string="Pack Group")
    md_code = fields.Char(string="MD Code")
    batch_no = fields.Char(string="Batch No")
    last_sync = fields.Datetime(string="Last Sync")
    scrap_datetime = fields.Datetime(string="Scrap Datetime")
    scrap_status = fields.Char(string="Scrap Status")