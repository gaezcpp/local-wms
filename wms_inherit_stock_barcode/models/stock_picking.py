from odoo import models, api


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _sync_packaging_lines(self):
        Packaging = self.env['product.packaging.sap']
        PickingPackaging = self.env['picking.packaging.line']

        # prefetch all moves
        all_moves = self.mapped('move_ids').filtered(lambda m: m.product_id)
        if not all_moves:
            return

        all_templates = all_moves.mapped('product_id.product_tmpl_id')

        packaging_data = Packaging.search([
            ('product_id', 'in', all_templates.ids),
            ('company_id', 'in', self.mapped('company_id').ids)
        ])

        packaging_map = {(p.product_id.id, p.company_id.id): p for p in packaging_data}

        create_vals = []

        for picking in self:
            moves = picking.move_ids.filtered(lambda m: m.product_id)
            if not moves:
                continue

            existing_products = set(picking.product_packaging_ids.mapped('product_id').ids)

            origin_picking = self.env['stock.picking'].sudo().search([
                ('name', '=', picking.origin),
                ('picking_type_id.production_only', '=', True)
            ], limit=1)

            packaging_type = (
                origin_picking.picking_type_id.packaging_type_id
                if origin_picking else picking.picking_type_id.packaging_type_id
            )

            for move in moves:
                tmpl_id = move.product_id.product_tmpl_id.id

                if tmpl_id in existing_products:
                    continue

                packaging = packaging_map.get((tmpl_id, picking.company_id.id))
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
                    'move_type_sap': packaging_type.move_type_sap,
                })

        if create_vals:
            PickingPackaging.create(create_vals)

    def button_validate(self):
        res = super().button_validate()
        next_pickings = self.mapped('move_ids.move_dest_ids.picking_id').filtered(lambda p: p)
        (self | next_pickings)._sync_packaging_lines()
        return res