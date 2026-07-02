from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import requests
import json
import logging
import re

_logger = logging.getLogger(__name__)

class StockSAP(models.Model):
    _name = 'stock.sap'
    _description = 'Stock SAP'
    _rec_name = 'product_id'
    
    product_id = fields.Many2one(comodel_name='product.product', string="Product")
    product_uom_id = fields.Many2one(comodel_name='uom.uom', string="Units")
    location_id = fields.Many2one(comodel_name='stock.location', string="Location")
    company_id = fields.Many2one(comodel_name='res.company', string="Company")
    odoo_stock = fields.Float(string="Odoo Stock")
    unrestricted_stock = fields.Float(string="Unrestricted Stock")
    quality_inspection_stock = fields.Float(string="Quality Inspection Stock")
    blocked_stock = fields.Float(string="Blocked Stock")
    
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
    def cron_synchronize_sap_stock(self):
        data_list = self._fetch_sap_data(
            config_key='query_stock_sap',
            cron_name='cron_synchronize_sap_stock',
        )
        if not data_list:
            return True
        _logger.info(f"TOTAL DATA cron_synchronize_sap_stock: {len(data_list)}")
        
        stock_sap = self.env['stock.sap'].sudo()
        companies = self.env['res.company'].sudo()
        product_template = self.env['product.product'].sudo()
        stock_location = self.env['stock.location'].sudo()
        unit_of_measure = self.env['uom.uom'].sudo()
        
        for data in data_list:
            company_registry = data.get('WERKS')
            if company_registry:
                company_id = companies.search([('company_registry', '=', company_registry),('sync_wms', '=', True)], limit=1)
                if not company_id:
                    continue
                
            product_code = (data.get('MATNR') or '').lstrip('0')
            if product_code:
                product_id = product_template.search([('default_code', '=', product_code),('company_id', '=', company_id.id)], limit=1)
                if not product_id:
                    continue
            
            unit = data.get('MEINS') or ''
            if unit:
                if unit.upper() == 'KG':
                    unit = 'kg'
                uom_id = unit_of_measure.search([('name', '=', unit)], limit=1)
                if not uom_id:
                    continue
            
            location_code = data.get('LGORT')
            if location_code:
                location_id = stock_location.search([
                    ('barcode', '=', location_code.upper()),
                    ('company_id', '=', company_id.id)
                ], limit=1)
                if not location_id:
                    continue
            
            odoo_stock = 0.0
            product_variant = self.env['product.product'].sudo().search([
                ('default_code', '=', product_code),
                ('company_id', '=', company_id.id),
            ], limit=1)
            if product_variant and location_id:
                odoo_stock = float(product_variant.with_context(location=location_id.id).qty_available)
                # odoo_stock = float(
                #     product_variant.with_context(
                #         location=location_id.id,
                #         compute_child=True
                #     ).qty_available
                # )
            unrestricted_stock = float(data.get('LABST')) or 0.0
            quality_inspection_stock = float(data.get('INSME')) or 0.0
            blocked_stock = float(data.get('SPEME')) or 0.0
            
            vals = {
                'product_id': product_id.id,
                'product_uom_id': uom_id.id,
                'location_id': location_id.id,
                'company_id': company_id.id,
                'odoo_stock': odoo_stock,
                'unrestricted_stock': unrestricted_stock,
                'quality_inspection_stock': quality_inspection_stock,
                'blocked_stock': blocked_stock,
            }
            
            existing_stock_sap = stock_sap.search([
                ('product_id', '=', product_id.id),
                ('location_id', '=', location_id.id),
                ('company_id', '=', company_id.id)
            ], limit=1)
            if not existing_stock_sap:
                stock_sap.create(vals)
                _logger.info(f"STOCK SAP {existing_stock_sap.product_id.default_code} CREATED")
            else:
                existing_stock_sap.write(vals)
                _logger.info(f"STOCK SAP {existing_stock_sap.product_id.default_code} UPDATED")