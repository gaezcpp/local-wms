from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class InheritStockPackage(models.Model):
    _inherit = 'stock.package'
    
    #PINDAH KE BASE
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
    
    def _reserved_packages(self):
        for rec in self.picking_ids:
            if rec.state in ('confirmed', 'assigned'):
                raise ValidationError(f"Packages tidak bisa dilakukan perubahan status karena ada Transfer pada {rec.name}")            
    
    def action_qi(self):
        self._reserved_packages()
        for rec in self:
            if rec.state != 'QI':
                rec.state = 'QI'
    
    def action_blocked(self):
        self._reserved_packages()
        for rec in self:
            if rec.state != 'Blocked':
                rec.state = 'Blocked'
    
    def action_uu(self):
        self._reserved_packages()
        for rec in self:
            if rec.state != 'UU':
                rec.state = 'UU'