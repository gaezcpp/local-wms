from odoo import models, fields, api
from odoo.exceptions import ValidationError
import requests
import json
import logging
_logger = logging.getLogger(__name__)

class PmAnalysis(models.Model):
    _name = 'pm.analysis'
    _description = 'Plan Maintenance WO Analysis'
    _rec_name = 'name'
    
    name = fields.Char(string="Name")
    code = fields.Char(string="Code")
    need_desc = fields.Boolean(string="Need Description?")
    active = fields.Boolean(string="Active", default=True)
    company_id = fields.Many2one(comodel_name="res.company", string="Company")
    
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
    def cron_synhtonize_wo_analysis(self):
        data_list = self._fetch_sap_data(
            config_key='query_wo_analysis',
            cron_name='cron_synhtonize_wo_analysis',
        )
        if not data_list:
            return True
        _logger.info(f"TOTAL DATA cron_synhtonize_wo_analysis: {len(data_list)}")
        
        analysis_model = self.env['pm.analysis'].sudo()
        company_model = self.env['res.company'].sudo()
        
        for data in data_list:
            grdtx = data.get('GRDTX')
            grund = data.get('GRUND')
            werks = data.get('WERKS')
            
            company = company_model.search([('company_registry', '=', werks),('sync_pm', '=', True)], limit=1)
            if not company:
                continue
            
            vals = {
                'name': grdtx,
                'code': grund,
                'company_id': company.id,
            }
            
            existing_analysis = analysis_model.search([('code', '=', grund),('company_id', '=', company.id)], limit=1)
            if not existing_analysis:
                analysis_model.create(vals)
                _logger.info(f"Analysis {grund} Created from Cron")
            else:
                if self._needs_update(existing_analysis, vals):
                    existing_analysis.write(vals)
                    _logger.info(f"Analysis {existing_analysis.code} Updated")