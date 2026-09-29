from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import datetime
from collections import defaultdict
import requests
import json
import logging
_logger = logging.getLogger(__name__)

class TaggingProblem(models.Model):
    _name = 'tagging.problem'
    _description = 'Tagging Problem'
    _rec_name = 'code'
    _order = 'id desc'
    
    name = fields.Char(string="Name")
    code = fields.Char(string="Code", index=True)
    code_group = fields.Char(string="Code Group")
    sap_synchronize = fields.Boolean(string="SAP Synchronize", default=False)
    
    
    @api.model
    def cron_synchronize_sap_tagging_problem(self):
        icp = self.env['ir.config_parameter'].sudo()
        x_i_api_key = icp.get_param('x_i_api_key') or icp.get_param('x_i_api_key_tagging')
        ip_sap_rfc = icp.get_param('ip_sap_rfc') or icp.get_param('ip_sap_rfc_tagging')
        query_tagging_problem_sap = icp.get_param('query_tagging_problem_sap')
        if not query_tagging_problem_sap:
            raise ValidationError("query_tagging_problem_sap belum disetting!")
        
        headers = {
            "x-i-api-key": str(x_i_api_key),
            "Content-Type": "application/json"
        }
        url = f"{ip_sap_rfc}/api/v1/zfm-query-data"
        body = {
            "I_QUERY": str(query_tagging_problem_sap),
            "I_MOD": "CRON cron_synchronize_sap_tagging_problem"
        }
        
        try:
            response = requests.post(url=url, headers=headers, data=json.dumps(body))
            res = response.json()
        except Exception as e:
            raise ValidationError(str(e))
        
        if res.get('error'):
            raise ValidationError(json.dumps(res.get('error')))
        
        if not res.get('success'):
            return True
        
        data_list = res.get('data', [])
        problem_model = self.env['tagging.problem'].sudo()
        
        for data in data_list:
            code = data.get('CODE') or ''
            kurztext = data.get('KURZTEXT') or ''
            code_group = data.get('CODEGROUP') or data.get('CODEGRUPPE')
            if not code:
                continue
            
            vals = {
                'code': code,
                'name': kurztext,
                'code_group': code_group,
                'sap_synchronize': True,
            }
            
            existing_problem = problem_model.search([('code', '=', code)], limit=1)
            if not existing_problem:
                problem_model.create(vals)
                _logger.info(f"Problem SAP {code} Created")
            else:
                existing_problem.write(vals)
            