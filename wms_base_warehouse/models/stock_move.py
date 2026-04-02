from odoo import models, fields, api


class StockMove(models.Model):
    _inherit = 'stock.move'
    
    product_packaging_id = fields.Many2one(comodel_name='product.packaging.sap', string="Product Packaging")
    qty_packaging_sap = fields.Float(string="Qty Packaging", default=0.0)
    
    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        moves._update_over_delivery()
        moves._sync_product_packaging()
        return moves

    def write(self, vals):
        res = super().write(vals)
        if any(field in vals for field in ['product_id', 'picking_id', 'qty_packaging_sap']):
            self._sync_product_packaging()
        if any(field in vals for field in ['quantity', 'product_uom_qty']):
            self._update_over_delivery()
        return res
    
    def _update_over_delivery(self):
        for move in self:
            picking = move.picking_id
            if not picking:
                continue

            over = False
            for m in picking.move_ids:
                if m.quantity != m.product_uom_qty:
                    over = True
                    break

            picking.over_delivery = over

    def _action_assign(self):
        moves_uu = self.filtered(lambda m: m.picking_id.picking_type_id.uu_only)
        moves_normal = self - moves_uu
        res = True
        if moves_normal:
            res = super(StockMove, moves_normal)._action_assign()
        if moves_uu:
            res = super(StockMove, moves_uu.with_context(uu_only=True))._action_assign()
        return res

    def _sync_product_packaging(self):
        packaging_model = self.env['product.packaging.sap']
        products = self.mapped('product_id.product_tmpl_id')
        packaging_map = {
            p.product_id.id: p
            for p in packaging_model.search([('product_id', 'in', products.ids)])
        }

        for picking in self.mapped('picking_id'):
            if not picking:
                continue

            move_products = picking.move_ids.mapped('product_id.product_tmpl_id')
            lines_to_remove = picking.product_packaging_ids.filtered(lambda l: l.product_id not in move_products)
            if lines_to_remove:
                lines_to_remove.unlink()

            for move in picking.move_ids:
                packaging = packaging_map.get(move.product_id.product_tmpl_id.id)
                move.product_packaging_id = packaging.id if packaging else False
                existing_line = picking.product_packaging_ids.filtered(lambda x: x.product_id.id == move.product_id.product_tmpl_id.id)

                if not packaging:
                    if existing_line:
                        existing_line.unlink()
                    continue

                vals = {
                    'picking_id': picking.id,
                    'product_id': move.product_id.product_tmpl_id.id,
                    'product_uom_desc': packaging.product_uom_desc,
                    'packaging_code': packaging.packaging_code,
                    'packaging_desc': packaging.packaging_desc,
                    'qty_packaging_sap': move.qty_packaging_sap,
                    'company_id': picking.company_id.id,
                }

                if existing_line:
                    existing_line.write(vals)
                else:
                    self.env['picking.packaging.line'].create(vals)