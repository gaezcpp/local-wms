from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class InheritStockQuant(models.Model):
    _inherit = 'stock.quant'

    inbound_date = fields.Datetime(string="Inbound Date", tracking=True)
    exp_group = fields.Datetime(string="Exp Group", tracking=True)
    uom_bag_id = fields.Many2one('uom.uom',  tracking=True)
    bag_qty = fields.Float(string="Bag", tracking=True)
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._prepare_bag_vals(vals)

        records = super().create(vals_list)
        records._recompute_package_pallet_status()
        return records

    def write(self, vals):
        if 'product_id' in vals or 'quantity' in vals:
            for rec in self:
                rec._prepare_bag_vals(vals)

        res = super().write(vals)
        self._recompute_package_pallet_status()
        return res
    
    def _recompute_package_pallet_status(self):
        param = self.env['ir.config_parameter'].sudo().get_param('pembagi_pallet')
        if not param:
            raise ValidationError("pembagi_pallet belum disetting!")

        try:
            pembagi_pallet = float(param)
        except:
            raise ValidationError("pembagi_pallet bukan angka!")

        if pembagi_pallet == 0:
            raise ValidationError("pembagi_pallet tidak boleh 0!")

        packages = self.mapped('package_id').filtered(lambda p: p)
        for pkg in packages:
            pallet_status = 'eceran'
            quants = pkg.contained_quant_ids.filtered(lambda q: q.quantity > 0)

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

            if pkg.pallet_status != pallet_status:
                pkg.pallet_status = pallet_status
    
    def _prepare_bag_vals(self, vals):
        product_id = vals.get('product_id')
        quantity = vals.get('quantity')
        if product_id is None and quantity is None:
            return vals

        if product_id:
            product = self.env['product.product'].sudo().browse(product_id)
        else:
            product = self.product_id

        qty = quantity if quantity is not None else self.quantity
        uom_bag = product.uom_bag_id if product else False
        vals['uom_bag_id'] = uom_bag.id if uom_bag else False

        if uom_bag and uom_bag.relative_factor and qty:
            vals['bag_qty'] = qty / uom_bag.relative_factor
        else:
            vals['bag_qty'] = 0.0

        return vals