from odoo import models, fields, api
from odoo.exceptions import ValidationError


class InheritBaseStockMoveLine(models.Model):
    _inherit = 'stock.move.line'
    
    production_line_id = fields.Many2one(comodel_name='production.line', string="Line")
    first_count = fields.Float(string="First Count")
    last_count = fields.Float(string="Last Count")
    detail_text = fields.Char(string="Detail Text")
    
    @api.model_create_multi
    def create(self, vals_list):
        locked_fields = ['production_line_id', 'first_count', 'last_count', 'detail_text']
        for vals in vals_list:
            has_custom = any(vals.get(f) for f in locked_fields)
            if has_custom and not self._is_prod_in(vals):
                raise ValidationError("Production fields hanya boleh diisi pada PROD-IN")
            if not has_custom:
                origin = self._get_origin_move_line(vals)
                if origin:
                    vals['production_line_id'] = origin.production_line_id.id
                    vals['first_count'] = origin.first_count
                    vals['last_count'] = origin.last_count
                    vals['detail_text'] = origin.detail_text
        return super().create(vals_list)

    def write(self, vals):
        locked_fields = ['production_line_id', 'first_count', 'last_count', 'detail_text']
        if any(f in vals for f in locked_fields):
            for rec in self:
                if not rec._is_prod_in():
                    raise ValidationError("Production fields hanya boleh diedit pada PROD-IN")
        return super().write(vals)
    
    def _is_prod_in(self, vals=None):
        picking = False
        if vals and vals.get('picking_id'):
            picking = self.env['stock.picking'].browse(vals['picking_id'])
        elif self.picking_id:
            picking = self.picking_id
        elif self.move_id and self.move_id.picking_id:
            picking = self.move_id.picking_id
        return picking and picking.picking_type_id.sequence_code == 'PROD-IN'

    def _get_origin_move_line(self, vals):
        move_id = vals.get('move_id')
        if not move_id:
            return False
        move = self.env['stock.move'].browse(move_id)
        if not move.move_orig_ids:
            return False
        lines = move.move_orig_ids.mapped('move_line_ids')
        return lines[:1] if lines else False