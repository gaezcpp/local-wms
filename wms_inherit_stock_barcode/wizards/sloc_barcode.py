from odoo import models, fields, api
from odoo.exceptions import ValidationError


class SlocBarcode(models.TransientModel):
    _name = 'sloc.barcode'
    _description = 'SLOC Barcode'
    
    
    