from odoo import models, fields, api
from datetime import datetime
import pytz

class InheritBaseStockPicking(models.Model):
    _inherit = 'stock.picking'
    
    po_sap_id = fields.Many2one(comodel_name='production.order.sap', string="PO SAP", tracking=True)

    def now_jakarta(self):
        tz = pytz.timezone('Asia/Jakarta')
        now_jakarta = datetime.now(tz)
        # return now_jakarta.date()
        return now_jakarta

    @api.onchange('po_sap_id')
    def _onchange_po_sap_product(self):
        for rec in self:
            if not rec.po_sap_id:
                continue

            product = rec.po_sap_id.product_id
            rec.move_ids = [(5, 0, 0)]
            rec.move_ids = [(0, 0, {
                'product_id': product.id,
            })]
            
    def _prepare_backorder_picking_vals(self):
        print("_prepare_backorder_picking_vals KEPANGGIL")
        self.ensure_one()
        vals = super()._prepare_backorder_picking_vals()

        prod_shift = self.production_shift_id

        if not prod_shift:
            now = self.now_jakarta().time()
            prod_shift = self.env['production.shift'].sudo().search([
                ('date_start', '<=', now),
                ('date_end', '>=', now),
            ], limit=1)

        vals.update({
            'production_shift_id': prod_shift.id if prod_shift else False,
            'po_sap_id': self.po_sap_id.id,
        })

        return vals

    def button_validate(self):
        res = super().button_validate()
        for picking in self:
            next_moves = picking.move_ids.mapped('move_dest_ids')
            next_pickings = next_moves.mapped('picking_id').filtered(lambda p: p)
            if not next_pickings:
                continue
            
            prod_shift = False
            right_now = self.now_jakarta()
            now_hour = right_now.strftime('%H%M')
            print(f"RIGHT {right_now} NOW HOUR {now_hour}")
            if picking.production_shift_id:
                print(f"MASUK SINI")
                prod_shift = picking.production_shift_id
            else:
                prod_shift = self.env['production.shift'].sudo().search([
                    ('date_start', '<=', now_hour),
                    ('date_end', '>=', now_hour),
                ], limit=1)
                print(f"SINI 2222222222 {prod_shift}")
            picking.production_shift_id = prod_shift.id
            
            for next_picking in next_pickings:
                next_picking.write({
                    'production_shift_id': prod_shift.id,
                    'po_sap_id': picking.po_sap_id.id,
                })
        return res