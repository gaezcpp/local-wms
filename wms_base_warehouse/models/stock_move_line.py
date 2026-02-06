from odoo import models, fields, api
from odoo.exceptions import ValidationError


class InheritBaseStockMoveLine(models.Model):
    _inherit = 'stock.move.line'
    
    production_line_id = fields.Many2one(comodel_name='production.line', string="Line")
    first_count = fields.Float(string="First Count")
    last_count = fields.Float(string="Last Count")
    detail_text = fields.Char(string="Detail Text")
    production_only = fields.Boolean(string="Production Only", related='picking_type_id.production_only')
    
    # @api.model_create_multi
    # def create(self, vals_list):
    #     locked_fields = ['production_line_id', 'first_count', 'last_count', 'detail_text']
    #     for vals in vals_list:
    #         has_custom = any(vals.get(f) for f in locked_fields)
    #         if has_custom and not self._is_prod_in(vals):
    #             raise ValidationError("Production fields hanya boleh diisi pada PROD-IN")
    #     return super().create(vals_list)

    # def write(self, vals):
    #     locked_fields = ['production_line_id', 'first_count', 'last_count', 'detail_text']
    #     if any(f in vals for f in locked_fields):
    #         for rec in self:
    #             if not rec._is_prod_in():
    #                 raise ValidationError("Production fields hanya boleh diedit pada PROD-IN")
    #     return super().write(vals)
    
    def _is_prod_in(self, vals=None):
        picking = False
        if vals and vals.get('picking_id'):
            picking = self.env['stock.picking'].browse(vals['picking_id'])
        elif self.picking_id:
            picking = self.picking_id
        elif self.move_id and self.move_id.picking_id:
            picking = self.move_id.picking_id
        return picking and picking.picking_type_id.sequence_code == 'PROD-IN'
    
    @api.onchange('production_line_id', 'first_count', 'last_count', 'detail_text')
    def _onchange_prod_in_fields(self):
        for rec in self:
            if not rec._is_prod_in():
                raise ValidationError("Production fields hanya boleh diedit pada PROD-IN")