from odoo import api, fields, models
from odoo.addons.wms_base_warehouse.models.uom_uom import InheritUomUom as _WbwUomUom


class FoodUomUom(models.Model):
    _inherit = 'uom.uom'

    # Non-stored, no dependencies: uom.uom carries no company_id of its own
    # (UoMs are shared across companies), so -- like _get_fields_stock_barcode
    # below -- this falls back to the acting user's company on every read
    # instead of being related through a field path.
    wms_type = fields.Selection([
        ('FOOD', 'FOOD'),
        ('FEED', 'FEED'),
    ], string="WMS Type", compute='_compute_wms_type')

    @api.depends()
    def _compute_wms_type(self):
        wms_type = self.env.company.wms_type
        for uom in self:
            uom.wms_type = wms_type

    def _get_fields_stock_barcode(self):
        # uom.uom carries no company_id of its own (UoMs are shared across
        # companies), so -- like stock_rule.py's _get_stock_move_values --
        # fall back to the acting user's company to decide FOOD vs FEED.
        if self.env.company.wms_type == 'FOOD':
            return super(_WbwUomUom, self)._get_fields_stock_barcode()
        return super(FoodUomUom, self)._get_fields_stock_barcode()
