from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class InhStockPackage(models.Model):
    _name = 'stock.package'
    _inherit = ['stock.package', 'mail.thread', 'mail.activity.mixin']
    
    pallet_status = fields.Selection([
        ('full_pallet', 'Full Pallet'),
        ('eceran', 'Eceran'),
    ], string="Pallet Status", default=False)
    yellow_tag = fields.Selection([
        ('ready', 'Ready'),
        ('hold', 'Hold'),
    ], string="Yellow Tag", default='ready', tracking=True)
    is_reserved = fields.Boolean(string="Is Reserved", compute='_compute_is_reserved')
    
    def action_ready(self):
        for rec in self:
            if rec.yellow_tag != 'ready':
                rec.yellow_tag = 'ready'
                
    def action_hold(self):
        for rec in self:
            if rec.yellow_tag != 'hold':
                rec.yellow_tag = 'hold'
                
    def _compute_is_reserved(self):
        for rec in self:
            domain = [
                '|',
                ('package_id', '=', rec.id),
                ('result_package_id', '=', rec.id),
                ('picking_id.picking_type_id.uu_only', '=', True),
                ('state', 'not in', ['done', 'cancel'])
            ]
            move_line_count = self.env['stock.move.line'].sudo().search_count(domain)
            rec.is_reserved = move_line_count > 0