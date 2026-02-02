from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class InheritStockQuant(models.Model):
    _inherit = 'stock.quant'

    inbound_date = fields.Datetime(string="Inbound Date", tracking=True)
    exp_group = fields.Datetime(string="Exp Group", tracking=True)
    
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

    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        res._recompute_package_pallet_status()
        return res

    def write(self, vals):
        res = super().write(vals)
        self._recompute_package_pallet_status()
        return res