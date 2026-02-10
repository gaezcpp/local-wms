from odoo import models, fields, api


class InheritStockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    uom_bag_id = fields.Many2one('uom.uom')
    bag_qty = fields.Float(string="Bag")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            rec = self.new(vals)
            self._prepare_bag_vals(rec, vals)
        moves = super().create(vals_list)
        return moves

    def write(self, vals):
        if 'quantity' in vals or 'move_id' in vals:
            for rec in self:
                rec._prepare_bag_vals(rec, vals)
        
        res = super().write(vals)
        return res
    
    def _prepare_bag_vals(self, rec, vals):
        if 'move_id' in vals:
            move = self.env['stock.move'].browse(vals['move_id'])
            product = move.product_id
        else:
            product = rec.move_id.product_id

        if 'quantity' in vals:
            qty = vals['quantity']
        else:
            qty = rec.quantity

        uom_bag_id = False
        bag_qty = 0.0

        if product and qty:
            uom_bag = product.uom_bag_id
            if uom_bag and uom_bag.factor:
                uom_bag_id = uom_bag.id
                bag_qty = qty / (uom_bag.factor / 1000)

        vals['uom_bag_id'] = uom_bag_id
        vals['bag_qty'] = bag_qty