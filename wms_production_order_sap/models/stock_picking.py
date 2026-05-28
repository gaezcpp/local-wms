from odoo import models, fields, api
from datetime import datetime
import pytz

class InheritBaseStockPicking(models.Model):
    _inherit = 'stock.picking'
    
    po_sap_id = fields.Many2one(comodel_name='production.order.sap', string="PO SAP", tracking=True)

    def now_jakarta(self):
        tz = pytz.timezone('Asia/Jakarta')
        return datetime.now(tz)

    def _prepare_backorder_picking_vals(self):
        self.ensure_one()
        vals = super()._prepare_backorder_picking_vals()

        prod_shift = self.production_shift_id

        if not prod_shift:
            now = self.now_jakarta().time()
            print(f"NOW PROD SHIFT {now}")
            prod_shift = self.env['production.shift'].sudo().search([
                ('date_start', '<=', now),
                ('date_end', '>=', now),
            ], limit=1)

        vals.update({
            'production_shift_id': prod_shift.id if prod_shift else False,
            'po_sap_id': self.po_sap_id.id,
        })

        return vals
    
    def action_confirm(self):
        res = super().action_confirm()
        Shift = self.env['production.shift'].sudo()
        for picking in self:
            right_now = self.now_jakarta()
            now_hour = right_now.strftime('%H%M')
            print(f"NOW HOUR {now_hour}")
            prod_shift = picking.production_shift_id
            if not prod_shift:
                prod_shift = Shift.search([
                    ('date_start', '<=', now_hour),
                    ('date_end', '>=', now_hour),
                ], limit=1)

            if prod_shift:
                picking.production_shift_id = prod_shift.id
        return res

    def button_validate(self):
        res = super().button_validate()

        Shift = self.env['production.shift'].sudo()

        for picking in self:
            next_pickings = picking.move_ids.move_dest_ids.picking_id.filtered(lambda p: p)

            right_now = self.now_jakarta()
            now_hour = right_now.strftime('%H%M')

            prod_shift = picking.production_shift_id
            if not prod_shift:
                prod_shift = Shift.search([
                    ('date_start', '<=', now_hour),
                    ('date_end', '>=', now_hour),
                ], limit=1)

            if prod_shift:
                picking.production_shift_id = prod_shift.id

            if next_pickings:
                next_pickings.write({
                    'production_shift_id': prod_shift.id if prod_shift else False,
                    'po_sap_id': picking.po_sap_id.id,
                })

        return res
    
    def _action_done(self):
        res = super()._action_done()
        for picking in self:
            picking._propagate_po_sap_to_quant()
            if picking.po_sap_id and picking.po_sap_id.state != 'teco':
                picking.po_sap_id.state = 'in_progress'
        return res
    
    # isi po_sap_id di stock.quant
    def _propagate_po_sap_to_quant(self):
        for picking in self.filtered(lambda p: p.po_sap_id and p.state == 'done'):
            quants = picking.move_line_ids.mapped('quant_id')
            quants = quants.filtered(lambda q: not q.po_sap_id)
            if quants:
                quants.write({'po_sap_id': picking.po_sap_id.id})