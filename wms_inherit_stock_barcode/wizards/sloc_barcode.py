from odoo import models, fields, api
from odoo.exceptions import ValidationError


class SlocBarcode(models.TransientModel):
    _name = 'sloc.barcode'
    _description = 'SLOC Barcode'
    
    picking_id = fields.Many2one('stock.picking', required=True)
    sloc_id = fields.Many2one('storage.location', required=True)

    def action_apply(self):
        self.ensure_one()

        picking = self.picking_id
        if not picking:
            raise ValidationError("Picking not found.")

        lines = self.env['picking.packaging.line'].sudo().search([('picking_id', '=', picking.id)])
        if not lines:
            raise ValidationError("No packaging lines found.")

        lines.write({
            'sloc_id': self.sloc_id.id,
            'sloc_packaging': self.sloc_id.name,
        })


        return {'type': 'ir.actions.act_window_close'}