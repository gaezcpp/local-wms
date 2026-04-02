from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import requests
import json
import logging
import re

_logger = logging.getLogger(__name__)


class InheritProductTemplate(models.Model):
    _inherit = 'product.template'

    sap_mm = fields.Boolean(string="SAP MM", tracking=True)

    @api.model
    def cron_synchronize_sap_master_data(self):
        icp = self.env['ir.config_parameter'].sudo()
        x_i_api_key = icp.get_param('x_i_api_key')
        ip_sap_rfc = icp.get_param('ip_sap_rfc')
        query_master_data_sap = icp.get_param('query_master_data_sap')

        if not x_i_api_key:
            raise ValidationError(_("x_i_api_key belum disetting!"))
        if not ip_sap_rfc:
            raise ValidationError(_("ip_sap_rfc belum disetting!"))
        if not query_master_data_sap:
            raise ValidationError(_("query_master_data_sap belum disetting!"))

        headers = {
            "x-i-api-key": str(x_i_api_key),
            "Content-Type": "application/json"
        }
        url = f"{str(ip_sap_rfc)}/api/v1/zfm-query-data"
        body = {
            "I_QUERY": str(query_master_data_sap),
            "I_MOD": "CRON cron_synchronize_sap_master_data"
        }

        response = requests.post(url=url, headers=headers, data=json.dumps(body), timeout=120)
        if response.status_code != 200:
            raise ValidationError(f"{response.status_code} | {response.text}")

        res = response.json()
        if res.get('error'):
            raise ValidationError(json.dumps(res.get('error')))
        if not res.get('success'):
            return True

        data_list = res.get('data', [])
        if not data_list:
            return True

        uom_kg = self.env['uom.uom'].sudo().search([('name', '=', 'kg')], limit=1)
        if not uom_kg:
            raise ValidationError(_("UoM kg tidak ditemukan"))

        grouped = {}
        for data in data_list:
            matnr = (data.get('MATNR') or "").lstrip('0')
            werks = data.get('WERKS')
            if not matnr or not werks:
                continue
            key = f"{matnr}__{werks}"
            grouped.setdefault(key, []).append(data)

        all_werks = list({k.split("__")[1] for k in grouped.keys()})
        companies = self.env['res.company'].sudo().search([
            ('company_registry', 'in', all_werks),
            ('sync_wms', '=', True),
        ])
        company_map = {c.company_registry: c for c in companies}

        all_matnr = list({k.split("__")[0] for k in grouped.keys()})
        existing_products = self.env['product.template'].sudo().search([('barcode', 'in', all_matnr)])
        product_map = {}
        for p in existing_products:
            product_map[(p.barcode, p.company_id.id)] = p

        uom_model = self.env['uom.uom'].sudo()
        category_model = self.env['product.category'].sudo()

        existing_uoms = uom_model.search([])
        uom_name_map = {u.name: u for u in existing_uoms}

        existing_categories = category_model.search([])
        category_map = {c.name: c for c in existing_categories}

        create_products = []
        write_map = {}
        for key, records in grouped.items():
            expiration = 0
            matnr, werks = key.split("__")
            company = company_map.get(werks)
            if not company:
                _logger.warning(f"SKIP PRODUCT {matnr} | COMPANY NOT FOUND WERKS={werks}")
                continue

            uom_ids = []
            bag_candidates = []
            categ_name = ""
            product_name = ""
            weight = 0.0

            for data in records:
                product_name = data.get('MAKTX') or product_name
                weight = float(data.get('NTGEW') or weight)
                categ_name = data.get('MTBEZ') or categ_name
                iprkz = (data.get('IPRKZ') or '').strip()
                mhdhb = int(data.get('MHDHB') or 0)
                print(f"XXXXXXXXX {product_name}\nDDDDDDDDDDDDDD{iprkz}=={mhdhb}")

                if iprkz == '1':
                    exp_val = int(mhdhb * 7)
                elif iprkz == '2':
                    exp_val = int(mhdhb * 30)
                elif iprkz == '3':
                    exp_val = int(mhdhb * 365)
                else:
                    exp_val = int(mhdhb)

                if exp_val > expiration:
                    expiration = exp_val

                if data.get('MTART') == "FERT" and data.get('SPRAS') == "E":
                    if data.get('MATKL') == "REMX":
                        categ_name = "REMIX"

                meinh = (data.get('MEINH') or "").strip()
                meins = (data.get('MEINS') or "").strip()

                uom_name = meinh
                if not any(c.isdigit() for c in meinh):
                    if meinh and meinh != meins:
                        uom_name = f"{meinh} {data.get('UMREZ') or '-'}"

                if not uom_name:
                    continue

                factor = float(data.get('UMREZ') or 1) / float(data.get('UMREN') or 1)

                existing_uom = uom_name_map.get(uom_name)
                vals_uom = {
                    'name': uom_name,
                    'relative_factor': factor,
                    'relative_uom_id': uom_kg.id,
                    'sap_synchronize': True,
                }

                if not existing_uom:
                    existing_uom = uom_model.create(vals_uom)
                    uom_name_map[uom_name] = existing_uom
                else:
                    existing_uom.write(vals_uom)

                if meinh.upper() != 'KG' and existing_uom.id not in uom_ids:
                    uom_ids.append(existing_uom.id)
                    
                meinh_upper = (meinh or "").upper()
                try:
                    if re.match(r'^B\d+$', meinh_upper):
                        bag_size = int(meinh_upper[1:])
                        bag_candidates.append((bag_size, existing_uom.id))
                    elif meinh_upper == "BAG":
                        umrez = float(data.get('UMREZ') or 1)
                        umren = float(data.get('UMREN') or 1)
                        if umren:
                            bag_size = int(umrez / umren)
                            bag_candidates.append((bag_size, existing_uom.id))
                except Exception:
                    pass

            uom_bag_id = False
            if bag_candidates:
                bag_candidates.sort(key=lambda x: x[0])
                uom_bag_id = bag_candidates[0][1]

            category = category_map.get(categ_name)
            categ_vals = {
                'name': categ_name,
                'packaging_reserve_method': 'full',
                'property_cost_method': 'standard',
                'property_valuation': 'periodic',
            }

            if not category:
                category = category_model.create(categ_vals)
                category_map[categ_name] = category
            else:
                category.write(categ_vals)
                
            lvorm = (records[0].get('LVORM') or '').strip()
            vals = {
                'name': product_name,
                'uom_id': uom_kg.id,
                'categ_id': category.id,
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
                'is_storable': True,
                'use_expiration_date': True,
                'tracking': 'lot',
                'expiration_time': expiration,
                'responsible_id': self.env.user.id,
                'company_id': company.id,
                'active': lvorm != 'X',
            }

            existing_product = product_map.get((matnr, company.id))
            if not existing_product:
                create_products.append(vals)
            else:
                write_map[existing_product.id] = vals

        if create_products:
            created = self.sudo().create(create_products)
            for p in created:
                product_map[(p.barcode, p.company_id.id)] = p

        for pid, vals in write_map.items():
            self.sudo().browse(pid).write(vals)