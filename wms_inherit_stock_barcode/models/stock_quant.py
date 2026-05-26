from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class InheritStockQuant(models.Model):
    _inherit = 'stock.quant'

    uom_bag_id = fields.Many2one('uom.uom', related='product_id.uom_bag_id', store=True)
    uom_pallet_id = fields.Many2one('uom.uom', related='product_id.uom_pallet_id', store=True)
    bag_qty = fields.Float(string="Bag")
    pallet_qty = fields.Float(string="Pallet Dummy")
    bag_dummy_qty = fields.Float(string="Bag Dummy")
    pallet_dummy_qty = fields.Float(string="Pallet Qty", compute='_compute_pallet_dummy_qty')

    def _skip_custom_logic(self):
        ctx = self.env.context
        return (
            ctx.get('inventory_mode') or
            ctx.get('install_mode') or
            ctx.get('install_demo') or
            ctx.get('test_enable')
        )
    
    @api.model_create_multi
    def create(self, vals_list):
        if self._skip_custom_logic():
            return super().create(vals_list)

        for vals in vals_list:
            self._prepare_bag_pallet_vals(vals)

        records = super().create(vals_list)
        records._recompute_package_pallet_status()

        return records
    
    def write(self, vals):
        if self._skip_custom_logic():
            return super().write(vals)

        if 'product_id' in vals or 'quantity' in vals or 'inventory_quantity' in vals:
            for rec in self:
                merged_vals = dict(vals)
                if 'product_id' not in merged_vals:
                    merged_vals['product_id'] = rec.product_id.id
                rec._prepare_bag_pallet_vals(merged_vals)
                vals_to_write = {}
                if 'bag_qty' in merged_vals:
                    vals_to_write['bag_qty'] = merged_vals['bag_qty']
                if 'pallet_qty' in merged_vals:
                    vals_to_write['pallet_qty'] = merged_vals['pallet_qty']
                if vals_to_write:
                    vals.update(vals_to_write)

        res = super().write(vals)
        self._recompute_package_pallet_status()

        return res
    
    def _recompute_package_pallet_status(self):
        param = self.env['ir.config_parameter'].sudo().get_param('pembagi_pallet')
        if not param:
            return

        try:
            pembagi_pallet = float(param)
        except:
            return

        if pembagi_pallet == 0:
            return

        packages = self.mapped('package_id').filtered(lambda p: p)
        for pkg in packages:
            quants = pkg.contained_quant_ids.filtered(lambda q: q.quantity > 0)
            if not quants:
                if pkg.pallet_status or not pkg.can_be_use:
                    pkg.sudo().write({
                        'pallet_status': False,
                        'can_be_use': True,
                    })
                continue
            
            pallet_status = 'eceran'
            product_ids = quants.mapped('product_id')
            if len(product_ids) == 1 and quants:
                quant = quants[0]
                uom_pallet = quant.product_id.uom_pallet_id

                if uom_pallet and quant.quantity:
                    try:
                        result = (uom_pallet.factor / pembagi_pallet) / quant.quantity
                        if abs(result - 1) < 0.00001:
                            pallet_status = 'full_pallet'
                    except ZeroDivisionError:
                        pass
            if not pallet_status:
                pallet_status = 'eceran'
            
            if pkg.pallet_status != pallet_status:
                pkg.sudo().write({
                    'pallet_status': pallet_status,
                    'can_be_use': pallet_status == 'eceran',
                })
    
    def _prepare_bag_pallet_vals(self, vals):
        product_id = vals.get('product_id')
        quantity = vals.get('quantity')

        if not product_id:
            return vals

        product = self.env['product.product'].sudo().browse(product_id)
        product_uom = product.uom_id

        qty = quantity if quantity is not None else 0.0

        uom_bag = product.uom_bag_id
        uom_pallet = product.uom_pallet_id

        vals['uom_bag_id'] = uom_bag.id if uom_bag else False
        vals['uom_pallet_id'] = uom_pallet.id if uom_pallet else False

        if uom_bag and qty and product_uom:
            vals['bag_qty'] = product_uom._compute_quantity(qty, uom_bag)

            if uom_pallet:
                vals['pallet_qty'] = product_uom._compute_quantity(qty, uom_pallet)
            else:
                vals['pallet_qty'] = 0.0
        else:
            vals['bag_qty'] = 0.0
            vals['pallet_qty'] = 0.0

        return vals
    
    @api.onchange('product_id')
    def _onchange_product_bag(self):
        for rec in self:
            product = rec.product_id
            if product:
                rec.uom_bag_id = product.uom_bag_id.id
                rec.uom_pallet_id = product.uom_pallet_id.id
            else:
                rec.uom_bag_id = False
                rec.uom_pallet_id = False
    
    @api.onchange('bag_dummy_qty')
    def _onchange_bag_dummy_qty(self):
        print("ONCHANGE BAG DUMMY")
        for line in self:
            if not line.bag_dummy_qty:
                line.inventory_quantity = 0.0
                continue
            print("BAG DUMMY", line)
            line.inventory_quantity = line.bag_dummy_qty * (line.uom_bag_id.factor / 1000)
    
    @api.depends('inventory_quantity', 'uom_pallet_id')
    def _compute_pallet_dummy_qty(self):
        for line in self:
            if line.inventory_quantity and line.uom_pallet_id:
                line.pallet_dummy_qty = line.inventory_quantity / (line.uom_pallet_id.factor / 1000)
            else:
                line.pallet_dummy_qty = 0.0