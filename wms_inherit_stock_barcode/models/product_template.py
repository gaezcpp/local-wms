from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class InheritProductTemplate(models.Model):
    _inherit = 'product.template'

    uom_bag_id = fields.Many2one('uom.uom', string="UoM Bag", tracking=True)
    uom_pallet_id = fields.Many2one('uom.uom', string="UoM Pallet", tracking=True)
    sap_mm = fields.Boolean(string="SAP MM", tracking=True)