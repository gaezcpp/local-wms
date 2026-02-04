from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class InheritStockPackage(models.Model):
    _inherit = 'stock.package'
    
    state = fields.Selection([
        ('QI', 'QI'),
        ('Blocked', 'Blocked'),
        ('UU', 'UU')], string="State", default="QI", tracking=True)
    pallet_status = fields.Selection([
        ('full_pallet', 'Full Pallet'),
        ('eceran', 'Eceran'),
    ], string="Pallet Status", default=False, tracking=True)
    
    def write(self, vals):
        res = super().write(vals)
        for rec in self:
            if rec.state in ('UU', 'Blocked'):
                if not rec.contained_quant_ids:
                    _logger.info(f"State pada {rec.name} otomatis berubah karena tidak ada quants")
                    rec.sudo().state = 'QI'
        return res
    
    def action_qi(self):
        for rec in self:
            if rec.state != 'QI':
                rec.state = 'QI'
    
    def action_blocked(self):
        for rec in self:
            if rec.state != 'Blocked':
                rec.state = 'Blocked'
    
    def action_uu(self):
        for rec in self:
            if rec.state != 'UU':
                rec.state = 'UU'