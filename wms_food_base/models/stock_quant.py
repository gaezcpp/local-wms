from odoo import api, fields, models
from odoo.addons.wms_base_warehouse.models.stock_quant import StockQuant as _WbwStockQuant
from odoo.addons.wms_inherit_stock_barcode.models.stock_quant import InheritStockQuant as _SbStockQuant


class FoodStockQuant(models.Model):
    _inherit = 'stock.quant'

    # Related, non-stored: lets the views below decide per-record whether to
    # show the FEED-customized arch or the plain Odoo one.
    wms_type = fields.Selection(related='company_id.wms_type', string="WMS Type", store=True, index=True)

    @api.model
    def _gather(self, product_id, location_id, lot_id=None, package_id=None, owner_id=None, strict=False, qty=None):
        company = location_id.company_id if location_id else self.env.company
        if company and company.wms_type == 'FOOD':
            return super(_WbwStockQuant, self)._gather(
                product_id, location_id, lot_id=lot_id, package_id=package_id,
                owner_id=owner_id, strict=strict, qty=qty
            )
        return super(FoodStockQuant, self)._gather(
            product_id, location_id, lot_id=lot_id, package_id=package_id,
            owner_id=owner_id, strict=strict, qty=qty
        )

    # wms_base_warehouse is the innermost FEED customization for write, so
    # jumping past it also skips wms_inherit_stock_barcode's write. create is
    # only customized by wms_inherit_stock_barcode.
    @api.model_create_multi
    def create(self, vals_list):
        food_vals, other_vals = [], []
        for vals in vals_list:
            company = self.env['res.company'].browse(vals['company_id']) if vals.get('company_id') else self.env.company
            (food_vals if company.wms_type == 'FOOD' else other_vals).append(vals)

        records = self.browse()
        if food_vals:
            records |= super(_SbStockQuant, self).create(food_vals)
        if other_vals:
            records |= super(FoodStockQuant, self).create(other_vals)
        return records

    def write(self, vals):
        food = self.filtered(lambda q: q.company_id.wms_type == 'FOOD')
        other = self - food

        res = True
        if food:
            res = super(_WbwStockQuant, food).write(vals) and res
        if other:
            res = super(FoodStockQuant, other).write(vals) and res
        return res

    # wms_inherit_stock_barcode now overrides _get_fields_stock_barcode,
    # get_stock_barcode_data_records and _get_stock_barcode_specific_data on
    # stock.quant to expose product_id.uom_bag_id and preload the bag UoM
    # record into the barcode cache, so Count Inventory lines can show their
    # quantity converted into the product's bag UoM -- the FEED-only display
    # feature that already exists for stock.picking/stock.move.line lines
    # (see wms_food_base/models/stock_picking.py and stock_move_line.py for
    # the analogous bypasses). wms_base_warehouse doesn't touch these three,
    # so wms_inherit_stock_barcode is the innermost
    # FEED layer here too; jump past it for FOOD so FOOD's Count Inventory
    # keeps showing plain native quantities, same as FOOD's picking lines.
    # stock.quant has no reliable single company at every call site here (the
    # method can run against an empty/mixed recordset while building the
    # initial screen load), so -- like uom.uom's own bypass -- fall back to
    # the acting user's company; the barcode app is a single-company session
    # by nature anyway.
    def _get_fields_stock_barcode(self):
        if self.env.company.wms_type == 'FOOD':
            return super(_SbStockQuant, self)._get_fields_stock_barcode()
        return super(FoodStockQuant, self)._get_fields_stock_barcode()

    def _get_stock_barcode_specific_data(self):
        if self.env.company.wms_type == 'FOOD':
            return super(_SbStockQuant, self)._get_stock_barcode_specific_data()
        return super(FoodStockQuant, self)._get_stock_barcode_specific_data()

    # This only exposes company_id.wms_type on the 'res.company' records sent
    # to the Barcode app's Count Inventory client (BarcodeQuantModel), so
    # wms_food_base/static/src/js/barcode_quant_model_patch.js can tell FOOD
    # and FEED apart without an extra RPC (mirrors why 'wms_type' is added
    # to stock.picking._get_fields_stock_barcode() for BarcodePickingModel).
    # The base data itself still needs the jump-past-FEED bypass above.
    def get_stock_barcode_data_records(self):
        if self.env.company.wms_type == 'FOOD':
            data = super(_SbStockQuant, self).get_stock_barcode_data_records()
        else:
            data = super(FoodStockQuant, self).get_stock_barcode_data_records()
        companies = data['records'].get('res.company')
        if companies:
            wms_types = {
                company.id: company.wms_type
                for company in self.env['res.company'].browse([c['id'] for c in companies])
            }
            for company in companies:
                company['wms_type'] = wms_types.get(company['id'])
        return data
