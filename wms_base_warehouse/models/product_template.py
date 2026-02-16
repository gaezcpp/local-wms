from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import requests
import json
import re
import logging
_logger = logging.getLogger(__name__)


class InheritProductTemplate(models.Model):
    _inherit = 'product.template'

    sap_mm = fields.Boolean(string="SAP MM", tracking=True)

    @api.model
    def cron_synchronize_sap_master_data(self):
        x_i_api_key = self.env['ir.config_parameter'].sudo().get_param('x_i_api_key')
        if not x_i_api_key:
            raise ValidationError("x_i_api_key belum disetting!")
        
        ip_sap_rfc = self.env['ir.config_parameter'].sudo().get_param('ip_sap_rfc')
        if not ip_sap_rfc:
            raise ValidationError("ip_sap_rfc belum disetting!")
        
        query_master_data_sap = self.env['ir.config_parameter'].sudo().get_param('query_master_data_sap')
        if not query_master_data_sap:
            raise ValidationError("query_master_data_sap belum disetting!")

        headers = {
            "x-i-api-key": str(x_i_api_key),
            "Content-Type": "application/json"
        }
        url = f"{str(ip_sap_rfc)}/api/v1/zfm-query-data"
        body = {
            "I_QUERY": str(query_master_data_sap),
            "I_MOD": "CRON cron_synchronize_sap_master_data"
        }

        response = requests.post(headers=headers, url=url, data=json.dumps(body))
        if response.status_code != 200:
            raise ValidationError(f"{response.status_code} | {response.text}")
        res = response.json()

        error = res.get('error', False)
        if error:
            raise ValidationError(json.dumps(error))

        if not res.get('success'):
            _logger.info("=== CRON cron_synchronize_sap_master_data NOT SUCCESS ===")
            return True

        data_list = res.get('data', [])
        _logger.info(f"TOTAL DATA MARA: {len(data_list)}")

        uom_kg = self.env['uom.uom'].sudo().search([('name', '=', 'kg')], limit=1)
        if not uom_kg:
            raise ValidationError("UoM kg tidak ditemukan")

        grouped = {}
        for data in data_list:
            matnr = data.get('MATNR')
            if not matnr:
                continue
            grouped.setdefault(matnr, []).append(data)

        _logger.info(f"TOTAL MATNR: {len(grouped)}")

        create_products = []
        write_map = {}

        for matnr, records in grouped.items():
            _logger.info(f"PROCESS MATNR: {matnr} | ROWS: {len(records)}")

            uom_ids = []
            bag_candidates = []
            categ_name = ""
            product_name = ""
            weight = 0

            for data in records:
                product_name = data.get('MAKTX', '')
                werks = data.get('WERKS', '')
                weight = data.get('NTGEW', 0)

                categ_name = data.get('MTBEZ', '')
                if data.get('MTART') == "FERT" and data.get('SPRAS') == "E":
                    if data.get('MATKL') == "REMX":
                        categ_name = "REMIX"

                meinh = data.get('MEINH', '')
                meins = data.get('MEINS', '')

                uom_name = meinh
                has_number = any(c.isdigit() for c in meinh)
                if not has_number:
                    if meinh != meins:
                        uom_name = f"{meinh or '-'} {data.get('UMREZ', '-')}"

                existing_uom = self.env['uom.uom'].sudo().search([('name', '=', uom_name)], limit=1)
                factor = float(data.get('UMREZ') or 1) / float(data.get('UMREN') or 1)

                uom_vals = {
                    'name': uom_name,
                    'relative_factor': factor,
                    'relative_uom_id': uom_kg.id,
                    'sap_synchronize': True,
                }

                if not existing_uom:
                    existing_uom = self.env['uom.uom'].sudo().create(uom_vals)
                    _logger.info(f"CREATE UOM: {uom_name}")
                else:
                    existing_uom.sudo().write(uom_vals)

                if meinh.upper() != 'KG':
                    if existing_uom.id not in uom_ids:
                        uom_ids.append(existing_uom.id)

                if re.match(r'^B\d+$', meinh.upper()):
                    try:
                        bag_candidates.append((int(re.findall(r'\d+', meinh)[0]), existing_uom.id))
                    except:
                        pass

            uom_bag_id = False
            if bag_candidates:
                bag_candidates.sort(key=lambda x: x[0])
                uom_bag_id = bag_candidates[0][1]
                _logger.info(f"UOM BAG SELECTED: {uom_bag_id}")

            existing_category = self.env['product.category'].sudo().search([('name', '=', categ_name)], limit=1)
            categ_vals = {
                'name': categ_name,
                'packaging_reserve_method': 'full',
                'property_cost_method': 'standard',
                'property_valuation': 'periodic',
            }

            if not existing_category:
                existing_category = self.env['product.category'].sudo().create(categ_vals)
                _logger.info(f"CREATE CATEGORY: {categ_name}")
            else:
                existing_category.sudo().write(categ_vals)
            
            existing_company = self.env['res.company'].sudo().search([('company_registry', '=', werks)], limit=1)
            if not existing_company:
                _logger.warning(f"SKIP PRODUCT {matnr} | COMPANY NOT FOUND WERKS={werks}")
                continue
            
            vals = {
                'name': product_name,
                'uom_id': uom_kg.id,
                'categ_id': existing_category.id,
                'weight': weight,
                'barcode': matnr,
                'default_code': matnr,
                'uom_bag_id': uom_bag_id,
                'uom_ids': [(6, 0, uom_ids)],
                'sale_ok': True,
                'purchase_ok': True,
                'sap_mm': True,
                'type': 'consu',
                'invoice_policy': 'order',
                'taxes_id': False,
                'supplier_taxes_id': False,
                'list_price': 0.0,
                'standard_price': 0.0,
                'purchase_method': 'receive',
                'is_storable': True,
                'use_expiration_date': True,
                'tracking': 'lot',
                'expiration_time': 365,
                'responsible_id': self.env.user.id,
                'company_id': existing_company.id if existing_company else False,
            }

            existing_product = self.env['product.template'].sudo().search([('barcode', '=', matnr),('company_id', '=', existing_company.id)], limit=1)

            if not existing_product:
                create_products.append(vals)
                _logger.info(f"QUEUE CREATE PRODUCT: {matnr}")
            else:
                write_map[existing_product.id] = vals
                _logger.info(f"QUEUE WRITE PRODUCT: {matnr}")

        if create_products:
            self.sudo().create(create_products)
            _logger.info(f"BULK CREATE PRODUCT: {len(create_products)}")

        for pid, vals in write_map.items():
            self.sudo().browse(pid).write(vals)

        _logger.info(f"TOTAL WRITE PRODUCT: {len(write_map)}")