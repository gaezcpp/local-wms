from odoo import api, models
from odoo.addons.wms_inherit_stock_barcode.models.product_product import ProductProduct as _SbProductProduct


class FoodProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def _get_fields_stock_barcode(self):
        # product.product's own company_id is False for products shared across
        # companies, so -- like uom_uom.py -- fall back to the acting user's
        # company to decide FOOD vs FEED.
        #
        # This must stay in lockstep with stock_move_line.py's bypass of the
        # same method: FOOD move lines never carry uom_bag_id/uom_pallet_id, so
        # the product records must not advertise them either. Otherwise the
        # barcode client's _getNewLineDefaultValues() patch (FEED, see
        # wms_inherit_stock_barcode/static/src/js/barcode_pickimg_model_patch.js)
        # would put a bag UoM on freshly scanned lines and render them in BOX
        # while reloaded lines -- read back without the field -- stay in kg.
        if self.env.company.wms_type == 'FOOD':
            return super(_SbProductProduct, self)._get_fields_stock_barcode()
        return super(FoodProductProduct, self)._get_fields_stock_barcode()
