from odoo import models, fields, api
from datetime import datetime
import pytz

class InheritBaseStockPicking(models.Model):
    _inherit = 'stock.picking'
    
    po_sap_id = fields.Many2one(comodel_name='production.order.sap', string="PO SAP", tracking=True)

    def now_jakarta(self):
        tz = pytz.timezone('Asia/Jakarta')
        return datetime.now(tz)

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
            # ambil next picking hasil chaining/backorder
            next_moves = picking.move_ids.mapped('move_dest_ids')
            next_pickings = next_moves.mapped('picking_id').filtered(lambda p: p)

            # tentukan shift
            right_now = self.now_jakarta()
            now_hour = right_now.strftime('%H%M')

            if picking.production_shift_id:
                prod_shift = picking.production_shift_id
            else:
                prod_shift = self.env['production.shift'].sudo().search([
                    ('date_start', '<=', now_hour),
                    ('date_end', '>=', now_hour),
                ], limit=1)

            picking.production_shift_id = prod_shift.id if prod_shift else False

            # update next picking
            for next_picking in next_pickings:
                next_picking.write({
                    'production_shift_id': prod_shift.id if prod_shift else False,
                    'po_sap_id': picking.po_sap_id.id,
                })

            # ✅ SYNC PACKAGING (CURRENT + NEXT)
            (picking | next_pickings)._sync_packaging_lines()

        return res
    
    def _sync_packaging_lines(self):
        Packaging = self.env['product.packaging.sap']
        PickingPackaging = self.env['picking.packaging.line']

        for picking in self:
            moves = picking.move_ids
            if not moves:
                continue

            product_templates = moves.mapped('product_id.product_tmpl_id')

            packaging_data = Packaging.search([
                ('product_id', 'in', product_templates.ids),
                ('company_id', '=', picking.company_id.id)
            ])

            packaging_map = {p.product_id.id: p for p in packaging_data}

            existing_products = set(
                picking.product_packaging_ids.mapped('product_id').ids
            )

            origin_picking = self.env['stock.picking'].sudo().search([
                ('name', '=', picking.origin),
                ('picking_type_id.production_only', '=', True)
            ], limit=1, order='id desc')

            packaging_type = (
                origin_picking.picking_type_id.packaging_type_id
                if origin_picking else
                picking.picking_type_id.packaging_type_id
            )

            create_vals = []

            for move in moves:
                tmpl_id = move.product_id.product_tmpl_id.id

                if tmpl_id in existing_products:
                    continue

                packaging = packaging_map.get(tmpl_id)
                if not packaging:
                    continue

                create_vals.append({
                    'picking_id': picking.id,
                    'product_id': tmpl_id,
                    'product_uom_desc': packaging.product_uom_desc,
                    'packaging_code': packaging.packaging_code,
                    'packaging_desc': packaging.packaging_desc,
                    'packaging_type_id': packaging_type.id,
                    'company_id': picking.company_id.id,
                })

            if create_vals:
                PickingPackaging.create(create_vals)