from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)

class InheritStockMove(models.Model):
    _inherit = 'stock.move'

    uom_bag_id = fields.Many2one('uom.uom',  related='product_id.uom_bag_id', store=True)
    uom_pallet_id = fields.Many2one('uom.uom', related='product_id.uom_pallet_id', store=True)
    bag_qty = fields.Float(string="Bag Qty", compute="_compute_bag_qty", store=True)
    pallet_qty = fields.Float(string="Pallet Qty", compute="_compute_pallet_qty", store=True)
    product_packaging_id = fields.Many2one(comodel_name='product.packaging.sap', string="Product Packaging")
    qty_packaging_sap = fields.Float(string="Qty Packaging", compute='_compute_qty_packaging_sap')
    
    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        moves.create_packaging_line()
        return moves

    def write(self, vals):
        res = super().write(vals)
        return res

    def _get_fields_stock_barcode(self):
        res = super()._get_fields_stock_barcode()
        return res + [
            'bag_qty',
            'pallet_qty',
            'uom_bag_id',
            'uom_pallet_id',
            'qty_packaging_sap',
        ]
        
    @api.depends('quantity', 'uom_bag_id', 'uom_pallet_id')
    def _compute_bag_qty(self):
        for line in self:
            if not line.uom_bag_id or not line.quantity:
                line.bag_qty = 0.0
                continue

            line.bag_qty = line.quantity / (line.uom_bag_id.factor / 1000)

    @api.depends('quantity', 'uom_pallet_id')
    def _compute_pallet_qty(self):
        for line in self:
            if not line.quantity or not line.uom_pallet_id:
                line.pallet_qty = 0.0
                continue

            line.pallet_qty = line.quantity / (line.uom_pallet_id.factor / 1000)
            
    @api.depends('move_line_ids.qty_packaging_sap')
    def _compute_qty_packaging_sap(self):
        for move in self:
            move.qty_packaging_sap = sum(move.move_line_ids.mapped('qty_packaging_sap'))
            
    def create_packaging_line(self):
        _logger.info("create_packaging_line KEPANGGIL")
        Packaging = self.env['product.packaging.sap']
        PickingPackaging = self.env['picking.packaging.line']
        pickings = self.mapped('picking_id').filtered(lambda p: p)
        if not pickings:
            return

        all_templates = self.mapped('product_id.product_tmpl_id')
        companies = pickings.mapped('company_id')

        packaging_data = Packaging.search([
            ('product_id', 'in', all_templates.ids),
            ('company_id', 'in', companies.ids)
        ])

        packaging_map = {
            (p.product_id.id, p.company_id.id): p
            for p in packaging_data
        }

        for picking in pickings:
            moves = picking.move_ids.filtered(lambda m: m.product_id)
            if not moves:
                continue

            existing_products = set(picking.product_packaging_ids.mapped('product_id').ids)
            origin_sloc_map = {}

            origin_moves = moves.filtered(lambda m: m.origin_returned_move_id)
            origin_pickings = origin_moves.mapped(
                'origin_returned_move_id.picking_id'
            )

            if origin_pickings:
                origin_lines = origin_pickings.mapped('product_packaging_ids')
                origin_sloc_map = {
                    line.product_id.id: line.sloc_id.id
                    for line in origin_lines if line.sloc_id
                }

            create_vals = []
            for move in moves:
                tmpl_id = move.product_id.product_tmpl_id.id

                if tmpl_id in existing_products:
                    continue

                packaging = packaging_map.get((tmpl_id, picking.company_id.id))
                if not packaging:
                    continue
                
                packaging_type = picking.picking_type_id.packaging_type_id
                create_vals.append({
                    'picking_id': picking.id,
                    'product_id': tmpl_id,
                    'product_uom_desc': packaging.product_uom_desc,
                    'packaging_code': packaging.packaging_code,
                    'packaging_desc': packaging.packaging_desc,
                    'company_id': picking.company_id.id,
                    'packaging_type_id': packaging_type.id,
                    'move_type_sap': packaging_type.move_type_sap,
                    'sloc_id': origin_sloc_map.get(tmpl_id, False),
                })

            if create_vals:
                PickingPackaging.create(create_vals)