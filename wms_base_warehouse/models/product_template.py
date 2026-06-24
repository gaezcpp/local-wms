from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from collections import defaultdict
import requests
import json
import logging
import re

_logger = logging.getLogger(__name__)


class InheritProductTemplate(models.Model):
    _inherit = 'product.template'

    sap_mm = fields.Boolean(string="SAP MM", tracking=True)
    product_wip_line_ids = fields.One2many(comodel_name='product.wip', inverse_name='parent_product_id')
    
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
            _logger.info(f"CRON {cron_name} NOT SUCCESS")
            return []

        data_list = res.get('data', [])
        _logger.info(f"CRON {cron_name} - TOTAL DATA: {len(data_list)}")
        return data_list
    
    @api.model
    def cron_synchronize_sap_master_data(self):
        data_list = self._fetch_sap_data(
            config_key='query_master_data_sap',
            cron_name='cron_synchronize_sap_master_data',
        )
        if not data_list:
            return True
        _logger.info(f"TOTAL DATA cron_synchronize_sap_master_data: {len(data_list)}")

        uom_model = self.env['uom.uom'].sudo()
        category_model = self.env['product.category'].sudo()
        company_model = self.env['res.company'].sudo()
        product_product_model = self.env['product.product'].sudo()

        uom_kg = uom_model.search([('name', '=', 'kg')], limit=1)
        if not uom_kg:
            raise ValidationError("UoM kg tidak ditemukan")

        grouped_data = defaultdict(list)
        for data in data_list:
            matnr = (data.get('MATNR') or "").lstrip('0')
            werks = data.get('WERKS')
            if not matnr or not werks:
                continue
            grouped_data[(matnr, werks)].append(data)

        all_werks = list({k[1] for k in grouped_data.keys()})
        companies = company_model.search([
            ('company_registry', 'in', all_werks),
            ('sync_wms', '=', True),
        ])
        company_map = {c.company_registry: c for c in companies}

        # FIX: Search globally for default_code AND barcode, and include archived products
        all_matnr = list({k[0] for k in grouped_data.keys()})
        existing_products = product_product_model.with_context(active_test=False).search([
            '|', ('default_code', 'in', all_matnr),
                 ('barcode', 'in', all_matnr)
        ])
        
        existing_pp_map = {}
        for p in existing_products:
            c_id = p.company_id.id
            if p.default_code:
                existing_pp_map[(p.default_code, c_id)] = p
            if p.barcode:
                existing_pp_map[(p.barcode, c_id)] = p
            
            # FIX: If product is global (no company), map it to all valid companies to avoid duplicate barcode errors
            if not c_id:
                for comp in companies:
                    if p.default_code:
                        existing_pp_map[(p.default_code, comp.id)] = p
                    if p.barcode:
                        existing_pp_map[(p.barcode, comp.id)] = p

        uom_name_map = {u.name: u for u in uom_model.search([])}
        category_map = {c.name: c for c in category_model.search([])}

        # FIX: Use dictionary to deduplicate product creations in the same batch
        pending_creates = {}
        write_map = {}

        for key, records in grouped_data.items():
            matnr, werks = key
            company = company_map.get(werks)
            
            if not company:
                continue

            expiration = 0
            uom_ids = []
            bag_candidates = []
            categ_name = ""
            product_name = ""
            weight = 0.0
            lvorm = (records[0].get('LVORM') or '').strip()

            for data in records:
                product_name = data.get('MAKTX') or product_name
                weight = float(data.get('NTGEW') or weight)
                categ_name = data.get('MTBEZ') or categ_name
                iprkz = (data.get('IPRKZ') or '').strip()
                mhdhb = int(data.get('MHDHB') or 0)

                exp_val = 0
                if iprkz == '1': exp_val = int(mhdhb * 7)
                elif iprkz == '2': exp_val = int(mhdhb * 30)
                elif iprkz == '3': exp_val = int(mhdhb * 365)
                else: exp_val = int(mhdhb)
                expiration = max(expiration, exp_val)

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
                    'sap_name': meinh,
                }

                if not existing_uom:
                    existing_uom = uom_model.create(vals_uom)
                    uom_name_map[uom_name] = existing_uom
                else:
                    existing_uom.write(vals_uom)

                if meinh.upper() != 'KG' and existing_uom.id not in uom_ids:
                    uom_ids.append(existing_uom.id)

                meinh_upper = (meinh or "").upper()
                uom_name_upper = (uom_name or "").upper()
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
                    # elif re.match(r'^BOX\s*(\d+)$', meinh_upper):
                    #     bag_size = int(re.match(r'^BOX\s*(\d+)$', meinh_upper).group(1))
                    #     bag_candidates.append((bag_size, existing_uom.id))
                    else:
                        match = re.search(r'\d+', uom_name_upper)
                        if match:
                            bag_size = int(match.group())
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

            vals = {
                'name': product_name,
                'uom_id': uom_kg.id,
                'categ_id': category.id,
                'weight': weight,
                'default_code': matnr,
                'uom_bag_id': uom_bag_id,
                'uom_ids': [(6, 0, uom_ids)] if uom_ids else False,
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
                'active': lvorm != 'X',
            }

            existing_pp = existing_pp_map.get((matnr, company.id))

            if existing_pp:
                write_map[existing_pp.product_tmpl_id.id] = vals
            else:
                create_key = (matnr, company.id)
                # FIX: Check if we already staged this exact product for creation in this batch
                if create_key not in pending_creates:
                    create_vals = dict(vals)
                    create_vals['barcode'] = matnr
                    create_vals['company_id'] = company.id
                    pending_creates[create_key] = create_vals

        # Flatten pending creates back into a list
        create_products = list(pending_creates.values())

        if create_products:
            self.sudo().create(create_products)
            _logger.info(f"cron_synchronize_sap_master_data CREATED {len(create_products)} templates")

        for pid, vals in write_map.items():
            self.sudo().browse(pid).write(vals)
            
        if write_map:
            _logger.info(f"cron_synchronize_sap_master_data UPDATED {len(write_map)} templates")
            
        return True