from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import requests
import json
import logging

_logger = logging.getLogger(__name__)


class InheritResPartner(models.Model):
    _inherit = 'res.partner'

    sap_synchronize = fields.Boolean(string="SAP Synchronize", default=False, tracking=True)
    cust_mobile = fields.Char(string="Mobile")

    @api.model
    def cron_synchronize_sap_partner(self):
        icp = self.env['ir.config_parameter'].sudo()

        x_i_api_key = icp.get_param('x_i_api_key')
        ip_sap_rfc = icp.get_param('ip_sap_rfc')
        query_master_customer_sap = icp.get_param('query_master_customer_sap')

        if not x_i_api_key:
            raise ValidationError("x_i_api_key belum disetting!")
        if not ip_sap_rfc:
            raise ValidationError("ip_sap_rfc belum disetting!")
        if not query_master_customer_sap:
            raise ValidationError("query_master_customer_sap belum disetting!")

        headers = {
            "x-i-api-key": str(x_i_api_key),
            "Content-Type": "application/json"
        }

        url = f"{str(ip_sap_rfc)}/api/v1/zfm-query-data"
        body = {
            "I_QUERY": str(query_master_customer_sap),
            "I_MOD": "CRON cron_synchronize_sap_partner"
        }

        try:
            response = requests.post(url=url, headers=headers, data=json.dumps(body),)
        except Exception as e:
            raise ValidationError(str(e))

        res = response.json()

        if res.get('error'):
            raise ValidationError(json.dumps(res.get('error')))

        if not res.get('success'):
            _logger.info("=== CRON cron_synchronize_sap_partner NOT SUCCESS ===")
            return True

        data_list = res.get('data', [])
        _logger.info(f"TOTAL DATA KNA1 : {len(data_list)}")

        Partner = self.env['res.partner'].sudo()
        Country = self.env['res.country'].sudo()

        country_cache = {c.code: c.id for c in Country.search([])}

        for data in data_list:
            ref = data.get('KUNNR')
            if not ref:
                continue

            name = data.get('NAME1') or ''
            if not name:
                _logger.warning(f"KUNNR {ref} skipped karena NAME1 kosong")
                continue

            street = data.get('STRAS') or ''
            city = data.get('ORT01') or ''
            district = data.get('ORT02') or ''
            postal_code = data.get('PSTLZ') or ''
            country_code = data.get('LAND1') or ''
            phone = data.get('TELF1') or ''
            mobile = data.get('TELF2') or ''
            loevm = data.get('LOEVM') or ''

            vals = {
                'ref': ref,
                'name': name,
                'street': street,
                'street2': district,
                'city': city,
                'zip': postal_code,
                'country_id': country_cache.get(country_code),
                'phone': phone,
                'cust_mobile': mobile,
                'sap_synchronize': True,
                # additional
                'type': 'contact',
                'company_type': 'person',
                'active': False if loevm == 'X' else True,
            }

            partner = Partner.search([('ref', '=', ref)], limit=1)

            if not partner:
                new_partner = Partner.create(vals)
                new_partner.message_post(body=f"Partner {ref} Created from Cron")
                _logger.info(f"Partner {ref} Created")
            else:
                partner.write(vals)
                # _logger.info(f"Partner {ref} Updated")