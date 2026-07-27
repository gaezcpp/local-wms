from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import datetime
import requests
import json
import logging
_logger = logging.getLogger(__name__)


class StorageLocation(models.Model):
    _name = 'storage.location'
    _description = 'Storage Location'
    _rec_name = 'code'
    _order = 'id desc'
    
    active = fields.Boolean(string="Active", default=True)
    name = fields.Char(string="Name")
    code = fields.Char(string="Code", index=True)
    sap_sync = fields.Boolean(string="SAP Sync")
    company_id = fields.Many2one(comodel_name='res.company', string="Company", default=lambda self: self.env.company)
    
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
    def cron_synchronize_sap_storage_location(self):
        data_list = self._fetch_sap_data(
            config_key='query_storage_location_sap',
            cron_name='cron_synchronize_sap_storage_location',
        )
        if not data_list:
            return True
        _logger.info(f"TOTAL DATA cron_synchronize_sap_storage_location: {len(data_list)}")
        
        storage_location = self.env['storage.location'].sudo()
        companies = self.env['res.company'].sudo()
        
        for data in data_list:
            code = data.get('LGORT') or ''
            if not code or code == '':
                continue
            
            company_registry = data.get('WERKS') or ''
            if company_registry:
                company_id = companies.search([
                    ('company_registry', '=', company_registry),
                    ('sync_wms', '=', True),
                ], limit=1)
                if not company_id:
                    continue
            
            sloc_name = data.get('LGOBE') or ''
            
            vals = {
                'active': True,
                'name': sloc_name,
                'code': code,
                'sap_sync': True,
                'company_id': company_id.id,
            }
            
            existing_storage_location = storage_location.search([
                ('code','=',code),
                ('company_id','=',company_id.id)
            ],limit=1)
            if not existing_storage_location:
                storage_location.create(vals)
                _logger.info(f"Production Line {code} Created")
            else:
                existing_storage_location.write(vals)