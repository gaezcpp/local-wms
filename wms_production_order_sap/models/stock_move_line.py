from odoo import models, fields, api


class StockMoveLineProduction(models.Model):
    _inherit = 'stock.move.line'
    
    valid_wip_product_ids = fields.Many2many(comodel_name='product.product', compute='_compute_valid_wip_product_ids')
    
    # Untuk Domain ADD PRODUCT
    @api.depends('picking_id.po_sap_id.product_id', 'picking_id.po_sap_id.product_id.product_wip_line_ids')
    def _compute_valid_wip_product_ids(self):
        for line in self:
            if line.picking_id and line.picking_id.po_sap_id and line.picking_id.po_sap_id.product_id:
                main_product_id = line.picking_id.po_sap_id.product_id.id
                wip_product_ids = line.picking_id.po_sap_id.product_id.product_wip_line_ids.mapped('product_id.id')
                all_valid_ids = list(set([main_product_id] + wip_product_ids))
                line.valid_wip_product_ids = [(6, 0, all_valid_ids)]
            else:
                line.valid_wip_product_ids = False