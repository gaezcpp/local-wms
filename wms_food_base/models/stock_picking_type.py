from odoo import fields, models


class FoodStockPickingType(models.Model):
    _inherit = 'stock.picking.type'

    # Related, non-stored: lets the views below decide per-record whether to
    # show the FEED-customized arch or the plain Odoo one.
    wms_type = fields.Selection(related='company_id.wms_type', string="WMS Type", store=True, index=True)
