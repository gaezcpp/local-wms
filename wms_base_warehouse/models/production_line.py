from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import datetime
import requests
import json
import logging
_logger = logging.getLogger(__name__)
class ProductionLineCustom(models.Model):
    _name = 'production.line'
    _description = 'Production Line'
    _rec_name = 'name'
    
    active = fields.Boolean(string="Active", default=True)
    code = fields.Char(string="Code", index=True)
    name = fields.Char(string="Name")
    sap_sync = fields.Boolean(string="SAP Sync")
    prod_code = fields.Char(string="Prod Code", index=True)
    company_id = fields.Many2one(comodel_name='res.company', string="Company", default=lambda self: self.env.company)
    
    def _get_fields_stock_barcode(self):
        return ['id', 'code', 'name', 'prod_code']
    
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
    def cron_synchronize_sap_production_line(self):
        data_list = self._fetch_sap_data(
            config_key='query_production_line_sap',
            cron_name='cron_synchronize_sap_production_line',
        )
        if not data_list:
            return True
        _logger.info(f"TOTAL DATA cron_synchronize_sap_production_line: {len(data_list)}")
        
        production_line = self.env['production.line'].sudo()
        companies = self.env['res.company'].sudo()
        
        for data in data_list:
            code = data.get('ZKEY2') or ''
            if not code or code == '':
                continue
            
            company_registry = data.get('ZKEY1') or ''
            if company_registry:
                company_id = companies.search([
                    ('company_registry', '=', company_registry),
                    ('sync_wms', '=', True),
                ], limit=1)
                if not company_id:
                    continue
            
            pl_name = data.get('ZKEY3') or ''
            prod_code = data.get('ZKEY4') or ''
            
            vals = {
                'active': True,
                'code': code,
                'name': pl_name,
                'prod_code': prod_code,
                'sap_sync': True,
                'company_id': company_id.id,
            }
            
            existing_production_line = production_line.search([
                ('code','=',code),
                ('company_id','=',company_id.id)
            ],limit=1)
            if not existing_production_line:
                production_line.create(vals)
                _logger.info(f"Production Line {code} Created")
            else:
                existing_production_line.write(vals)