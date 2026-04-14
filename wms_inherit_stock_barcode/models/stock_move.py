from odoo import models, fields, api
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
        for picking in pickings:
            moves = picking.move_ids
            if not moves:
                continue

            product_templates = moves.mapped('product_id.product_tmpl_id')
            packaging_data = Packaging.search([
                ('product_id', 'in', product_templates.ids),
                ('company_id', '=', picking.company_id.id)
            ])

            packaging_map = {p.product_id.id: p for p in packaging_data}
            existing_products = set(picking.product_packaging_ids.mapped('product_id').ids)
            origin_picking = self.env['stock.picking'].sudo().search([
                ('name', '=', picking.origin),
                ('picking_type_id.production_only', '=', True)
            ], limit=1, order='id desc')

            packaging_type = (origin_picking.picking_type_id.packaging_type_id if origin_picking else picking.picking_type_id.packaging_type_id)
            
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
                    'company_id': picking.company_id.id,
                    'packaging_type_id': packaging_type.id,
                    # 'sloc_packaging': packaging_type.default_location_src_id.sloc_name,
                    # 'sloc_id': packaging_type.default_location_src_id.sloc_id.id,
                    'move_type_sap': packaging_type.move_type_sap,
                })

            if create_vals:
                PickingPackaging.create(create_vals)