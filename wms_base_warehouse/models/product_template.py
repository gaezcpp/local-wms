from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class InheritProductTemplate(models.Model):
    _inherit = 'product.template'

    sap_mm = fields.Boolean(string="SAP MM", tracking=True)