from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class InheritStockQuant(models.Model):
    _inherit = 'stock.quant'

    inbound_date = fields.Datetime(string="Inbound Date", tracking=True)
    exp_group = fields.Datetime(string="Exp Group", tracking=True)
    
    def _recompute_package_pallet_status(self):
        pembagi_pallet = self.env['ir.config_parameter'].sudo().get_param('pembagi_pallet')
        if not pembagi_pallet:
            raise ValidationError("pembagi_pallet belum disetting!")
        
        packages = self.mapped('package_id').filtered(lambda p: p)
        for pkg in packages:
            pallet_status = 'eceran'
            quants = pkg.contained_quant_ids

            product_ids = quants.mapped('product_id')
            if len(product_ids) == 1 and quants:
                quant = quants[0]
                uom_pallet = quant.product_id.uom_pallet_id
                if (uom_pallet.factor / float(pembagi_pallet)) / quant.quantity == 1:
                    pallet_status = 'full_pallet'

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