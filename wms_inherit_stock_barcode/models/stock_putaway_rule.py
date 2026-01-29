from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class InheritStockPutawayRule(models.Model):
    _inherit = 'stock.putaway.rule'

    pallet_status = fields.Selection([
        ('full_pallet', 'Full Pallet'),
        ('eceran', 'Eceran'),
    ], string="Pallet Status", default=False, tracking=True)