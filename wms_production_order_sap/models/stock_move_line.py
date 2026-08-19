from odoo import models, fields, api


class StockMoveLineProduction(models.Model):
    _inherit = 'stock.move.line'
    
    valid_wip_product_ids = fields.Many2many(comodel_name='product.product', compute='_compute_valid_wip_product_ids')
    
    # Untuk Domain ADD PRODUCT
    @api.depends('picking_id.po_sap_id.product_id', 'picking_id.po_sap_id.product_id.product_wip_line_ids', 'picking_id.picking_type_id.warehouse_id')
    def _compute_valid_wip_product_ids(self):
        for line in self:
            if line.picking_id and line.picking_id.po_sap_id and line.picking_id.po_sap_id.product_id:
                # main_product_id = line.picking_id.po_sap_id.product_id.id
                picking_wh = line.picking_id.picking_type_id.warehouse_id
                valid_wip_lines = line.picking_id.po_sap_id.product_id.product_wip_line_ids.filtered(lambda x: x.warehouse_id and x.warehouse_id == picking_wh)
                wip_product_ids = valid_wip_lines.mapped('product_id.id')
                # all_valid_ids = list(set([main_product_id] + wip_product_ids))
                line.valid_wip_product_ids = [(6, 0, wip_product_ids)]
            else:
                line.valid_wip_product_ids = False

    def _get_fields_stock_barcode(self):
        # Dipakai Barcode app untuk memvalidasi product hasil scan pada
        # picking type production_only (domain yang sama dengan Add Product).
        res = super()._get_fields_stock_barcode()
        if 'valid_wip_product_ids' not in res:
            res.append('valid_wip_product_ids')
        return res