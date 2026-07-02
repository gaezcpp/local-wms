from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import requests
import json
import logging
_logger = logging.getLogger(__name__)


class ProductPackagingSAP(models.Model):
    _name = 'product.packaging.sap'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Product Packaging SAP'
    _rec_name = 'packaging_code'
    _order = 'id desc'
    
    product_id = fields.Many2one(comodel_name='product.product', string="Product")
    product_uom_desc = fields.Char(string="UoM")
    packaging_code = fields.Char(string="Packaging")
    packaging_desc = fields.Char(string="Packaging Description")
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
    def cron_synchronize_sap_product_packaging(self):
        data_list = self._fetch_sap_data(
            config_key='query_product_packaging_sap',
            cron_name='cron_synchronize_sap_product_packaging',
        )
        if not data_list:
            return True
        _logger.info(f"TOTAL DATA cron_synchronize_sap_product_packaging: {len(data_list)}")
        
        product_packaging_sap = self.env['product.packaging.sap'].sudo()
        companies = self.env['res.company'].sudo()
        
        for data in data_list:
            company_registry = data.get('PLANT') or ''
            if company_registry:
                company_id = companies.search([
                    ('company_registry', '=', company_registry),
                    ('sync_wms', '=', True),
                ], limit=1)
                if not company_id:
                    continue
            
            finish_good = (data.get('FNSH_GOOD') or "").lstrip('0')
            product_id = self.env['product.product'].sudo().search([('default_code', '=', finish_good)], limit=1)
            if not product_id:
                continue
            
            bag_uom = data.get('BAG_UOM') or ''
            pcklbl = data.get('PCKLBL') or ''
            pack_desc = data.get('PACK_DESC') or ''
            
            vals = {
                'product_id': product_id.id if product_id else False,
                'product_uom_desc': bag_uom,
                'packaging_code': pcklbl,
                'packaging_desc': pack_desc,
                'company_id': company_id.id if company_id else False,
            }
            
            existing_product_packaging_sap = product_packaging_sap.search([
                ('product_id', '=', product_id.id),
                ('packaging_code', '=', pcklbl)
            ], limit=1)
            if not existing_product_packaging_sap:
                new_product_packaging = product_packaging_sap.create(vals)
                new_product_packaging.message_post(body=f"PRODUCT PACKAGING SAP {product_packaging_sap} Created from Cron")
                _logger.info(f"PO SAP {product_packaging_sap} Created")
            else:
                existing_product_packaging_sap.write(vals)
                _logger.info(f"PO {existing_product_packaging_sap.product_id.default_code} Updated")