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
    _rec_name = 'code'
    
    active = fields.Boolean(string="Active", default=True)
    code = fields.Char(string="Code")
    name = fields.Char(string="Name")
    sap_sync = fields.Boolean(string="SAP Sync")
    company_id = fields.Many2one(comodel_name='res.company', string="Company", default=lambda self: self.env.company)
    
    @api.model
    def cron_synchronize_sap_production_line(self):
        icp = self.env['ir.config_parameter'].sudo()
        x_i_api_key = icp.get_param('x_i_api_key')
        ip_sap_rfc = icp.get_param('ip_sap_rfc')
        query_production_line_sap = icp.get_param('query_production_line_sap')
        
        if not x_i_api_key:
            raise ValidationError("x_i_api_key belum disetting!")
        if not ip_sap_rfc:
            raise ValidationError("ip_sap_rfc belum disetting!")
        if not query_production_line_sap:
            raise ValidationError("query_production_line_sap belum disetting!")
        
        headers = {
            "x-i-api-key": str(x_i_api_key),
            "Content-Type": "application/json"
        }
        
        url = f"{str(ip_sap_rfc)}/api/v1/zfm-query-data"
        body = {
            "I_QUERY": str(query_production_line_sap),
            "I_MOD": "CRON cron_synchronize_sap_production_line"
        }
        
        try:
            response = requests.post(url=url, headers=headers, data=json.dumps(body),)
        except Exception as e:
            raise ValidationError(str(e))
        
        res = response.json()
        
        if res.get('error'):
            raise ValidationError(json.dumps(res.get('error')))
        if not res.get('success'):
            _logger.info("=== CRON cron_synchronize_sap_production_line NOT SUCCESS ===")
            return True
        
        data_list = res.get('data', [])
        _logger.info(f"TOTAL DATA aufk: {len(data_list)}")
        
        production_line = self.env['production.line'].sudo()
        companies = self.env['res.company'].sudo()
        
        for data in data_list:
            code = data.get('ZKEY2') or ''
            if not code or code == '':
                _logger.info(f"CODE {code} SKIPPED!")
            
            company_registry = data.get('ZKEY1') or ''
            if company_registry:
                company_id = companies.search([
                    ('company_registry', '=', company_registry),
                    ('sync_wms', '=', True),
                ], limit=1)
                if not company_id:
                    _logger.info(f"company_id {company_id} SKIPPED")
                    continue
            
            pl_name = data.get('ZKEY3') or ''
            
            vals = {
                'active': True,
                'code': code,
                'name': pl_name,
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