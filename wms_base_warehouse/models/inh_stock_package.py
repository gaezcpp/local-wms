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
    
    def write(self, vals):
        old_values = {quant.id: quant.stock_type for quant in self}
        res = super(InhStockPackage, self).write(vals)
        if 'stock_type' in vals:
            self._log_stock_type_change(old_values)
        return res
    
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

    def _log_stock_type_change(self, old_values):
        for quant in self:
            old_type = old_values.get(quant.id)
            new_type = quant.stock_type
            if old_type != new_type and quant.package_id:
                message_body = f"Update Stock Type: Produk {quant.product_id.display_name} telah diubah dari {old_type or '-'} menjadi {new_type}."
                quant.package_id.message_post(body=message_body)