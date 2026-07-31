from odoo import api, fields, models
from odoo.addons.wms_base_warehouse.models.stock_picking import InheritBaseStockPicking as _WbwStockPicking
from odoo.addons.wms_production_order_sap.models.stock_picking import InheritBaseStockPicking as _PosStockPicking
from odoo.addons.wms_sale_order_sap.models.stock_picking import SaleStockPicking as _SosStockPicking
from odoo.addons.wms_inherit_stock_barcode.models.stock_picking import StockPicking as _SbStockPicking


class FoodStockPicking(models.Model):
    _inherit = 'stock.picking'

    # Related, non-stored: lets the views below decide per-record whether to
    # show the FEED-customized arch or the plain Odoo one.
    wms_type = fields.Selection(related='company_id.wms_type', string="WMS Type", store=True, index=True)

    # NOTE: every method below is customized for FEED by one or more of
    # wms_base_warehouse / wms_inherit_stock_barcode / wms_production_order_sap /
    # wms_sale_order_sap. For a FOOD company we jump straight past the
    # innermost (earliest-loaded) of those custom classes via super(), which
    # skips ALL addons_custom layers for that method and lands on native
    # Odoo behavior. For anything else (FEED or empty) we call super()
    # normally so the existing FEED chain runs unchanged.

    def action_confirm(self):
        food = self.filtered(lambda p: p.company_id.wms_type == 'FOOD')
        other = self - food

        res = True
        if food:
            res = super(_PosStockPicking, food).action_confirm() and res
        if other:
            res = super(FoodStockPicking, other).action_confirm() and res
        return res

    def button_validate(self):
        food = self.filtered(lambda p: p.company_id.wms_type == 'FOOD')
        other = self - food

        if food:
            res = super(_WbwStockPicking, food).button_validate()
            if isinstance(res, dict) or not other:
                return res
        if other:
            return super(FoodStockPicking, other).button_validate()
        return True

    def _create_backorder(self, backorder_moves=None):
        food = self.filtered(lambda p: p.company_id.wms_type == 'FOOD')
        other = self - food

        backorders = self.browse()
        if food:
            backorders |= super(_WbwStockPicking, food)._create_backorder(backorder_moves=backorder_moves)
        if other:
            backorders |= super(FoodStockPicking, other)._create_backorder(backorder_moves=backorder_moves)
        return backorders

    def copy(self, default=None):
        if self.company_id.wms_type == 'FOOD':
            return super(_WbwStockPicking, self).copy(default)
        return super(FoodStockPicking, self).copy(default)

    def _action_done(self):
        # NOTE: stock.picking._action_done() returns a plain bool (True), not
        # a recordset, so results must be combined with `and`, not `|=`.
        food = self.filtered(lambda p: p.company_id.wms_type == 'FOOD')
        other = self - food

        res = True
        if food:
            res = super(_PosStockPicking, food)._action_done() and res
        if other:
            res = super(FoodStockPicking, other)._action_done() and res
        return res

    @api.model_create_multi
    def create(self, vals_list):
        food_vals, other_vals = [], []
        for vals in vals_list:
            company = self.env['res.company'].browse(vals['company_id']) if vals.get('company_id') else self.env.company
            (food_vals if company.wms_type == 'FOOD' else other_vals).append(vals)

        records = self.browse()
        if food_vals:
            records |= super(_SosStockPicking, self).create(food_vals)
        if other_vals:
            records |= super(FoodStockPicking, self).create(other_vals)
        return records

    def write(self, vals):
        food = self.filtered(lambda p: p.company_id.wms_type == 'FOOD')
        other = self - food

        res = True
        if food:
            res = super(_SosStockPicking, food).write(vals) and res
        if other:
            res = super(FoodStockPicking, other).write(vals) and res
        return res

    # wms_inherit_stock_barcode is the only FEED layer overriding these three
    # (neither wms_base_warehouse, wms_production_order_sap nor
    # wms_sale_order_sap touch them), so it is also the innermost one here.

    def _get_fields_stock_barcode(self):
        # Pure field-name list (no per-record data), but the barcode app
        # always calls this on a same-company batch, so a single [0] check
        # is enough -- mirrors _get_new_picking_values() in stock_move.py.
        if self and self[0].company_id.wms_type == 'FOOD':
            res = super(_SbStockPicking, self)._get_fields_stock_barcode()
        else:
            res = super(FoodStockPicking, self)._get_fields_stock_barcode()
        # Needed client-side (barcode app OWL patches, see
        # wms_food_base/static/src/js/) so BarcodePickingModel.record.wms_type
        # is populated for both FOOD and FEED without an extra RPC.
        if 'wms_type' not in res:
            res.append('wms_type')
        return res

    def _get_stock_barcode_data(self):
        if self and self[0].company_id.wms_type == 'FOOD':
            return super(_SbStockPicking, self)._get_stock_barcode_data()
        return super(FoodStockPicking, self)._get_stock_barcode_data()

    def _pre_action_done_hook(self):
        # Native button_validate() calls self._pre_action_done_hook() (a
        # plain self-dispatch, not a super() call), so even though FOOD's
        # button_validate() above already jumps straight past every FEED
        # override of button_validate() itself, that dynamic dispatch still
        # resolves to wms_inherit_stock_barcode's _pre_action_done_hook
        # (production pallet confirmation wizard) unless it is bypassed here
        # too.
        food = self.filtered(lambda p: p.company_id.wms_type == 'FOOD')
        other = self - food

        if food:
            res = super(_SbStockPicking, food)._pre_action_done_hook()
            if res is not True or not other:
                return res
        if other:
            return super(FoodStockPicking, other)._pre_action_done_hook()
        return True

    # cron_synhronize_sap_sales_return (wms_base_warehouse) creates/updates
    # stock.picking/stock.move records straight from a raw SAP query keyed
    # by plant (WERKS), with no notion of wms_type at all -- there is no
    # "native Odoo" SAP sync to jump back to for FOOD. Instead we strip FOOD
    # companies' rows out of the payload here, before wms_base_warehouse's
    # own parsing loop (in the cron method itself) ever sees them.
    @api.model
    def _fetch_sap_data(self, config_key, cron_name):
        data_list = super()._fetch_sap_data(config_key, cron_name)
        if not data_list:
            return data_list

        werks_values = {row.get('WERKS') for row in data_list if row.get('WERKS')}
        if not werks_values:
            return data_list

        food_werks = set(self.env['res.company'].sudo().search([
            ('company_registry', 'in', list(werks_values)),
            ('wms_type', '=', 'FOOD'),
        ]).mapped('company_registry'))
        if not food_werks:
            return data_list

        return [row for row in data_list if row.get('WERKS') not in food_werks]
