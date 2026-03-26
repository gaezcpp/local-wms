from odoo import models, fields, api


class InheritBaseStockPicking(models.Model):
    _inherit = 'stock.picking'
    
    po_sap_id = fields.Many2one(comodel_name='production.order.sap', string="PO SAP", tracking=True)

    def button_validate(self):
        res = super().button_validate()
        for picking in self:
            next_moves = picking.move_ids.mapped('move_dest_ids')
            next_pickings = next_moves.mapped('picking_id').filtered(lambda p: p)
            if not next_pickings:
                continue

            origin_lines = picking.move_line_ids
            for next_picking in next_pickings:
                next_picking.write({
                    'production_shift_id': picking.production_shift_id.id,
                    'po_sap_id': picking.po_sap_id.id,
                })
                for line in next_picking.move_line_ids:
                    origin_line = origin_lines.filtered(lambda l: l.product_id.id == line.product_id.id and (not line.lot_id or l.lot_id.id == line.lot_id.id))
                    if not origin_line:
                        continue
                    origin_line = origin_line[0]
                    line.write({
                        'production_line_id': origin_line.production_line_id.id,
                        'first_count': origin_line.first_count,
                        'last_count': origin_line.last_count,
                        'detail_text': origin_line.detail_text,
                    })
        return res