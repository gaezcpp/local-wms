from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import datetime
import requests
import json
import logging
_logger = logging.getLogger(__name__)


class ProductionLineCustom(models.Model):
    _name = 'food.production.line'
    _description = 'Production Line'
    _rec_name = 'name'
    
    active = fields.Boolean(string="Active", default=True)
    code = fields.Char(string="Code", index=True)
    name = fields.Char(string="Name")
    sap_sync = fields.Boolean(string="SAP Sync")
    line_code = fields.Char(string="Line Code", index=True)
    company_id = fields.Many2one(comodel_name='res.company', string="Company", default=lambda self: self.env.company)
    
    def _get_fields_stock_barcode(self):
        return ['id', 'code', 'name', 'line_code']