from odoo import api, models


class FoodProductPackagingSap(models.Model):
    _inherit = 'product.packaging.sap'

    # product.packaging.sap is a pure SAP-staging model (no core Odoo
    # equivalent) and its records only carry FK references to core models,
    # never writes into them -- so there is no native behavior to jump back
    # to. It is still FEED-only staging data feeding FEED barcode/packaging
    # flows, so cron_synchronize_sap_product_packaging must not populate it
    # for FOOD companies either: strip their rows (PLANT) out of the payload
    # before wms_base_warehouse's own parsing loop runs.
    @api.model
    def _fetch_sap_data(self, config_key, cron_name):
        data_list = super()._fetch_sap_data(config_key, cron_name)
        if not data_list:
            return data_list

        plant_values = {row.get('PLANT') for row in data_list if row.get('PLANT')}
        if not plant_values:
            return data_list

        food_plants = set(self.env['res.company'].sudo().search([
            ('company_registry', 'in', list(plant_values)),
            ('wms_type', '=', 'FOOD'),
        ]).mapped('company_registry'))
        if not food_plants:
            return data_list

        return [row for row in data_list if row.get('PLANT') not in food_plants]
