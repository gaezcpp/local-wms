from odoo import api, models


class FoodStorageLocation(models.Model):
    _inherit = 'storage.location'

    # storage.location has no core Odoo equivalent, so cron_synchronize_sap_
    # storage_location (wms_base_warehouse) is not "customizing" a native
    # behavior we can jump back to; per the FOOD/FEED design this SAP sync
    # simply must not run for FOOD companies, so we strip their rows (WERKS)
    # out of the payload before wms_base_warehouse's own parsing loop runs.
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
