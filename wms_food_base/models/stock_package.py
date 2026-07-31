from odoo import fields, models


class FoodStockPackage(models.Model):
    _inherit = 'stock.package'

    # Related, non-stored: lets the views below decide per-record whether to
    # show the FEED-customized arch (wms_base_warehouse's inh_stock_package.py
    # / wms_inherit_stock_barcode's stock_package.py) or the plain Odoo one.
    # stock.package.company_id is itself computed+stored from quant_ids/
    # child_package_ids (see odoo/addons/stock/models/stock_package.py), so
    # this related field follows the same recompute chain automatically.
    wms_type = fields.Selection(related='company_id.wms_type', string="WMS Type", store=True, index=True)
