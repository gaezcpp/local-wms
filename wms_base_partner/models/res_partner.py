from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import requests
import json
import logging

_logger = logging.getLogger(__name__)


class InheritResPartner(models.Model):
    _inherit = 'res.partner'

    sap_synchronize = fields.Boolean(string="SAP Synchronize", default=False, tracking=True)
    plant_sap = fields.Boolean(string="Plant SAP", default=False, tracking=True)
    cust_mobile = fields.Char(string="Mobile")
    
    def _needs_update(self, model, vals):
        for field, new_val in vals.items():
            if field not in model._fields:
                continue

            field_def = model._fields[field]
            old_val = model[field]

            if field_def.type == 'many2one':
                old_id = old_val.id if old_val else False
                if old_id != new_val:
                    return True

            elif field_def.type in ('many2many', 'one2many'):
                if isinstance(new_val, list):
                    new_ids = set()
                    for cmd in new_val:
                        if cmd[0] == 6:
                            new_ids = set(cmd[2])
                        elif cmd[0] == 4:
                            new_ids.add(cmd[1])
                    old_ids = set(old_val.ids)
                    if old_ids != new_ids:
                        return True
                else:
                    if set(old_val.ids) != set(new_val):
                        return True

            else:
                if (old_val or False) != (new_val or False):
                    return True

        return False
    
    @api.model
    def _fetch_sap_data(self, config_key, cron_name):
        icp = self.env['ir.config_parameter'].sudo()
        x_i_api_key = icp.get_param('x_i_api_key')
        ip_sap_rfc = icp.get_param('ip_sap_rfc')
        query = icp.get_param(config_key)

        if not x_i_api_key:
            raise ValidationError("x_i_api_key belum disetting!")
        if not ip_sap_rfc:
            raise ValidationError("ip_sap_rfc belum disetting!")
        if not query:
            raise ValidationError(f"{config_key} belum disetting!")

        headers = {
            "x-i-api-key": str(x_i_api_key),
            "Content-Type": "application/json"
        }
        body = {
            "I_QUERY": str(query),
            "I_MOD": f"CRON {cron_name}"
        }
        try:
            response = requests.post(
                url=f"{ip_sap_rfc}/api/v1/zfm-query-data",
                headers=headers,
                data=json.dumps(body),
                timeout=240
            )
        except Exception as e:
            raise ValidationError(str(e))

        res = response.json()
        if res.get('error'):
            raise ValidationError(json.dumps(res.get('error')))
        if not res.get('success'):
            _logger.info(f"CRON {cron_name} NOT SUCCESS || {res}")
            return []

        data_list = res.get('data', [])
        _logger.info(f"CRON {cron_name} - TOTAL DATA: {len(data_list)}")
        return data_list

    @api.model
    def cron_synchronize_sap_partner(self):
        data_list = self._fetch_sap_data(
            config_key='query_master_customer_sap',
            cron_name='cron_synchronize_sap_partner',
        )
        if not data_list:
            return True
        _logger.info(f"TOTAL DATA cron_synchronize_sap_partner: {len(data_list)}")

        Partner = self.env['res.partner'].sudo()
        Country = self.env['res.country'].sudo()

        country_cache = {c.code: c.id for c in Country.search([])}
        all_refs = [d.get('KUNNR') for d in data_list if d.get('KUNNR')]
        existing_partners = Partner.search([('ref', 'in', all_refs)])
        partner_cache = {p.ref: p for p in existing_partners}

        for data in data_list:
            ref = data.get('KUNNR')
            if not ref:
                continue

            name = data.get('NAME1') or ''
            if not name:
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
                'type': 'contact',
                'company_type': 'person',
                'active': False if loevm == 'X' else True,
            }

            partner = partner_cache.get(ref)
            if not partner:
                new_partner = Partner.create(vals)
                new_partner.message_post(body=f"Partner {ref} Created from Cron")
                _logger.info(f"Partner {ref} Created")
                partner_cache[ref] = new_partner
            else:
                if self._needs_update(partner, vals):
                    partner.write(vals)
                    _logger.info(f"CUSTOMER {partner.ref} Updated")
                
    @api.model
    def cron_synchronize_sap_plan_as_partner(self):
        data_list = self._fetch_sap_data(
            config_key='query_plan_as_partner_sap',
            cron_name='cron_synchronize_sap_plan_as_partner',
        )
        if not data_list:
            return True
        _logger.info(f"TOTAL DATA cron_synchronize_sap_plan_as_partner: {len(data_list)}")
        
        Partner = self.env['res.partner'].sudo()
        Country = self.env['res.country'].sudo()
        country_cache = {c.code: c.id for c in Country.search([])}
        
        for data in data_list:
            ref = data.get('WERKS')
            if not ref:
                continue
            
            name = data.get('NAME1')
            if not name:
                continue
            
            street = data.get('STRAS')
            city = data.get('ORTO1')
            country_code = data.get('LAND1')
            
            vals = {
                'ref': ref,
                'name': name,
                'street': street,
                'city': city,
                'country_id': country_cache.get(country_code),
                'sap_synchronize': True,
                'plant_sap': True,
                # additional
                'type': 'contact',
                'company_type': 'person',
                'comment': 'Plant Created from Cron',
            }
            
            existing_plant = Partner.search([('ref', '=', ref)], limit=1)
            if not existing_plant:
                new_plant = Partner.create(vals)
                new_plant.message_post(body=f"PLANT {ref} Created from Cron")
                _logger.info(f"PLANT {ref} Created from Cron")
            else:
                if self._needs_update(existing_plant, vals):
                    existing_plant.write(vals)
                    _logger.info(f"PLAN {existing_plant.ref} Updated")