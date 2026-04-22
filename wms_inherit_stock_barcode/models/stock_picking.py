from odoo import models, fields, api
from odoo.exceptions import ValidationError

class StockPicking(models.Model):
    _inherit = 'stock.picking'
    
    sloc_filled = fields.Boolean(string="SLOC Filled", compute='_compute_sloc_filled', store=True)
    
    @api.depends('product_packaging_ids.sloc_id')
    def _compute_sloc_filled(self):
        for rec in self:
            lines = rec.product_packaging_ids
            rec.sloc_filled = bool(lines) and all(l.sloc_id for l in lines)
    
    def action_open_sloc_packaging_wizard(self):
        self.ensure_one()

        view = self.env.ref('wms_inherit_stock_barcode.view_sloc_packaging_wizard_form')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Set SLOC Packaging',
            'res_model': 'sloc.barcode',
            'views': [(view.id, 'form')],
            'target': 'new',
            'context': {
                'default_picking_id': self.id,
            }
        }
        
    def _prepare_packaging_lines_vals(self):
        Packaging = self.env['product.packaging.sap']

        all_moves = self.mapped('move_ids').filtered(lambda m: m.product_id)
        if not all_moves:
            return []

        all_templates = all_moves.mapped('product_id.product_tmpl_id')

        packaging_data = Packaging.search([
            ('product_id', 'in', all_templates.ids),
            ('company_id', 'in', self.mapped('company_id').ids)
        ])

        packaging_map = {(p.product_id.id, p.company_id.id): p for p in packaging_data}

        origins = self.mapped('origin')
        origin_pickings = self.env['stock.picking'].sudo().search([('name', 'in', origins)])
        origin_map = {p.name: p for p in origin_pickings}

        create_vals = []

        for picking in self:
            moves = picking.move_ids.filtered(lambda m: m.product_id)
            if not moves:
                continue

            existing_products = set(picking.product_packaging_ids.mapped('product_id').ids)

            origin_picking = origin_map.get(picking.origin)

            sloc_map = {}
            if origin_picking:
                sloc_map = {
                    line.product_id.id: line.sloc_id.id
                    for line in origin_picking.product_packaging_ids
                    if line.sloc_id
                }

            packaging_type = picking.picking_type_id.packaging_type_id

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
                    'company_id': picking.company_id.id,
                    'packaging_type_id': packaging_type.id,
                    'move_type_sap': packaging_type.move_type_sap,
                    'sloc_id': sloc_map.get(tmpl_id),
                })

        return create_vals

    def _sync_packaging_lines(self):
        vals_list = self._prepare_packaging_lines_vals()
        if vals_list:
            self.env['picking.packaging.line'].create(vals_list)
    
    def _check_all_sloc_filled(self):
        for picking in self:
            if picking.picking_packaging_type_id.production_only:
                lines = picking.product_packaging_ids
                if not lines:
                    continue

                missing = lines.filtered(lambda l: not l.sloc_id)
                if missing:
                    raise ValidationError(
                        f"SLOC belum lengkap untuk picking {picking.name}.\n\n"
                        f"Masukkan SLOC Packaging pada : {', '.join(missing.mapped('packaging_desc'))}"
                    )
    
    def button_validate(self):
        self._sync_packaging_lines()
        self._check_all_sloc_filled()
        res = super().button_validate()
        next_pickings = self.mapped('move_ids.move_dest_ids.picking_id').filtered(lambda p: p)
        if next_pickings:
            next_pickings._sync_packaging_lines()
        return res

    # SEBELOM SLOC PINDAH KE SCANNER
    # def _sync_packaging_lines(self):
    #     Packaging = self.env['product.packaging.sap']
    #     PickingPackaging = self.env['picking.packaging.line']

    #     # prefetch all moves
    #     all_moves = self.mapped('move_ids').filtered(lambda m: m.product_id)
    #     if not all_moves:
    #         return

    #     all_templates = all_moves.mapped('product_id.product_tmpl_id')

    #     packaging_data = Packaging.search([
    #         ('product_id', 'in', all_templates.ids),
    #         ('company_id', 'in', self.mapped('company_id').ids)
    #     ])

    #     packaging_map = {(p.product_id.id, p.company_id.id): p for p in packaging_data}

    #     create_vals = []

    #     for picking in self:
    #         moves = picking.move_ids.filtered(lambda m: m.product_id)
    #         if not moves:
    #             continue

    #         existing_products = set(picking.product_packaging_ids.mapped('product_id').ids)

    #         origin_picking = self.env['stock.picking'].sudo().search([
    #             ('name', '=', picking.origin),
    #             ('picking_type_id.production_only', '=', True)
    #         ], limit=1)

    #         packaging_type = (
    #             origin_picking.picking_type_id.packaging_type_id
    #             if origin_picking else picking.picking_type_id.packaging_type_id
    #         )

    #         for move in moves:
    #             tmpl_id = move.product_id.product_tmpl_id.id

    #             if tmpl_id in existing_products:
    #                 continue

    #             packaging = packaging_map.get((tmpl_id, picking.company_id.id))
    #             if not packaging:
    #                 continue

    #             create_vals.append({
    #                 'picking_id': picking.id,
    #                 'product_id': tmpl_id,
    #                 'product_uom_desc': packaging.product_uom_desc,
    #                 'packaging_code': packaging.packaging_code,
    #                 'packaging_desc': packaging.packaging_desc,
    #                 'packaging_type_id': packaging_type.id,
    #                 'company_id': picking.company_id.id,
    #                 'move_type_sap': packaging_type.move_type_sap,
    #             })

    #     if create_vals:
    #         PickingPackaging.create(create_vals)

    # def button_validate(self):
    #     res = super().button_validate()
    #     next_pickings = self.mapped('move_ids.move_dest_ids.picking_id').filtered(lambda p: p)
    #     (self | next_pickings)._sync_packaging_lines()
    #     return res