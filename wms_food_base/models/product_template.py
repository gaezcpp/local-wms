from odoo import api, fields, models


class FoodProductTemplate(models.Model):
    _inherit = 'product.template'

    # Related, non-stored: lets the views below decide per-record whether to
    # show the FEED-customized arch or the plain Odoo one. product.template's
    # own company_id is optional (False for products shared across
    # companies), in which case this stays False/falsy and the FEED arch is
    # kept -- the existing (safe) default for shared products.
    wms_type = fields.Selection(related='company_id.wms_type', string="WMS Type", store=True, index=True)

    # cron_synchronize_sap_master_data (wms_base_warehouse) creates/updates
    # product.template records straight from a raw SAP query keyed by plant
    # (WERKS) with no notion of wms_type at all -- there is no "native Odoo"
    # SAP sync to super()-jump back to for FOOD. Instead we strip FOOD
    # companies' rows out of the payload here, before wms_base_warehouse's
    # parsing loop (further down the MRO, inside this very method) ever sees
    # them: calling super() unchanged then only creates/updates FEED data.
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
