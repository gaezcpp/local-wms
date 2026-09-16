from collections import defaultdict
import json
import logging
import re

import requests

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class InheritProductTemplate(models.Model):
    _inherit = 'product.template'

    sap_sync = fields.Boolean(string="SAP Sync", tracking=True)
    uom_package_id = fields.Many2one('uom.uom', string="UoM Package", tracking=True)
    uom_pallet_id = fields.Many2one('uom.uom', string="UoM Pallet", tracking=True)
    
    @api.model
    def _needs_update(self, model, vals):
        for field, new_val in vals.items():
            if field not in model._fields:
                continue

            field_def = model._fields[field]
            old_val = model[field]

            if field_def.type == 'many2one':
                old_id = old_val.id if old_val else False
                if old_id != (new_val or False):
                    return True

            elif field_def.type in ('many2many', 'one2many'):
                if isinstance(new_val, list):
                    new_ids = set(old_val.ids)
                    for cmd in new_val:
                        if cmd[0] in (0, 1, 2, 3, 5):
                            return True
                        elif cmd[0] == 6:
                            new_ids = set(cmd[2])
                        elif cmd[0] == 4:
                            new_ids.add(cmd[1])
                    old_ids = set(old_val.ids)
                    if old_ids != new_ids:
                        return True
                else:
                    new_val_iterable = new_val if new_val else []
                    if set(old_val.ids) != set(new_val_iterable):
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
                url=f"{ip_sap_rfc.rstrip('/')}/api/v1/zfm-query-data",
                headers=headers,
                json=body,
                timeout=60,
            )
            response.raise_for_status()
            res = response.json()
        except requests.RequestException as error:
            raise ValidationError(_("Gagal mengambil data SAP: %s", error)) from error
        except ValueError as error:
            raise ValidationError(_("Respons SAP bukan JSON yang valid.")) from error

        if not isinstance(res, dict):
            raise ValidationError(_("Respons SAP harus berupa object JSON."))
        if res.get('error'):
            raise ValidationError(json.dumps(res.get('error')))
        if not res.get('success'):
            _logger.info("CRON %s NOT SUCCESS || %s", cron_name, res)
            return []

        data_list = res.get('data', [])
        if not isinstance(data_list, list):
            raise ValidationError(_("Data SAP harus berupa list."))
        _logger.info("CRON %s - TOTAL DATA: %s", cron_name, len(data_list))
        return data_list
    
    @api.model
    def cron_food_synchronize_sap_product(self):
        data_list = self._fetch_sap_data(
            config_key='query_food_product_template_sap',
            cron_name='cron_food_synchronize_sap_product',
        )
        if not data_list:
            return True
        _logger.info(
            "TOTAL DATA cron_food_synchronize_sap_product: %s", len(data_list)
        )

        uom_model = self.env['uom.uom'].sudo()
        category_model = self.env['product.category'].sudo()
        company_model = self.env['res.company'].sudo()
        product_product_model = self.env['product.product'].sudo()
        
        uom_kg = self.env.ref('uom.product_uom_kgm', raise_if_not_found=False)
        if not uom_kg:
            raise ValidationError("UoM kg tidak ditemukan")

        grouped_data = defaultdict(list)
        for data in data_list:
            matnr = (data.get('MATNR') or "").lstrip('0')
            werks = (data.get('WERKS') or '').strip()
            if not matnr or not werks:
                _logger.warning(
                    "Data produk SAP dilewati karena MATNR atau WERKS kosong: "
                    "MATNR=%s, WERKS=%s",
                    matnr,
                    werks,
                )
                continue
            grouped_data[(matnr, werks)].append(data)

        all_werks = list({k[1] for k in grouped_data.keys()})
        companies = company_model.search([('company_registry', 'in', all_werks)])
        company_map = {c.company_registry: c for c in companies}

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
            
            if not c_id:
                for comp in companies:
                    if p.default_code:
                        existing_pp_map[(p.default_code, comp.id)] = p
                    if p.barcode:
                        existing_pp_map[(p.barcode, comp.id)] = p

        uom_name_map = {u.name: u for u in uom_model.search([])}
        category_map = {c.name: c for c in category_model.search([])}

        pending_creates = {}
        write_map = {}

        for key, records in grouped_data.items():
            matnr, werks = key
            company = company_map.get(werks)
            
            if not company:
                _logger.warning(
                    "Produk SAP %s dilewati: company aktif untuk WERKS %s "
                    "tidak ditemukan",
                    matnr,
                    werks,
                )
                continue

            expiration = 0
            uom_ids = []
            bag_candidates = []
            lvorm = (records[0].get('LVORM') or '').strip()
            
            product_name = ""
            categ_name = ""
            weight = 0.0
            has_valid_conversion = False

            for data in records:
                product_name = (data.get('MAKTX') or '').strip() or product_name
                categ_name = (data.get('MTBEZ') or '').strip() or categ_name
                iprkz = (data.get('IPRKZ') or '').strip()
                try:
                    weight = float(data.get('NTGEW') or 0.0)
                    mhdhb = int(data.get('MHDHB') or 0)
                    umrez = float(data.get('UMREZ') or 1)
                    umren = float(data.get('UMREN') or 1)
                except (TypeError, ValueError):
                    _logger.warning(
                        "Konversi numerik produk SAP %s dilewati: UMREZ=%r, "
                        "UMREN=%r, NTGEW=%r, MHDHB=%r",
                        matnr,
                        data.get('UMREZ'),
                        data.get('UMREN'),
                        data.get('NTGEW'),
                        data.get('MHDHB'),
                    )
                    continue

                if umrez <= 0 or umren <= 0:
                    _logger.warning(
                        "Konversi UoM produk SAP %s dilewati: UMREZ dan UMREN "
                        "harus lebih dari nol",
                        matnr,
                    )
                    continue

                has_valid_conversion = True

                exp_val = 0
                if iprkz == '1': exp_val = int(mhdhb * 7)
                elif iprkz == '2': exp_val = int(mhdhb * 30)
                elif iprkz == '3': exp_val = int(mhdhb * 365)
                else: exp_val = int(mhdhb)
                expiration = max(expiration, exp_val)

                meins = (data.get('MEINS') or "").strip()
                vrkme = (data.get('VRKME') or "").strip()
                uom_name = vrkme
                
                if not any(c.isdigit() for c in vrkme):
                    if vrkme and vrkme != meins:
                        hasil_bagi = umrez / umren
                        if hasil_bagi.is_integer():
                            dibagi = int(hasil_bagi)
                        else:
                            dibagi = hasil_bagi
                        uom_name = f"{vrkme} {dibagi}"

                if not uom_name:
                    _logger.warning("UoM produk SAP %s kosong dan dilewati", matnr)
                    continue

                factor = umrez / umren
                existing_uom = uom_name_map.get(uom_name)
                vals_uom = {
                    'name': uom_name,
                    'relative_factor': factor,
                    'relative_uom_id': uom_kg.id,
                    'sap_sync': True,
                    'sap_name': vrkme,
                }

                if not existing_uom:
                    existing_uom = uom_model.create(vals_uom)
                    uom_name_map[uom_name] = existing_uom
                else:
                    if self._needs_update(existing_uom, vals_uom):
                        existing_uom.write(vals_uom)

                if vrkme.upper() != 'KG' and existing_uom.id not in uom_ids:
                    uom_ids.append(existing_uom.id)

                vrkme_upper = (vrkme or "").upper()
                uom_name_upper = (uom_name or "").upper()
                if re.fullmatch(r'MC\d+(?:\.\d+)?', vrkme_upper):
                    bag_candidates.append((float(vrkme_upper[2:]), existing_uom.id))
                elif vrkme_upper == "MC":
                    bag_candidates.append((factor, existing_uom.id))
                else:
                    match = re.search(r'\d+(?:\.\d+)?', uom_name_upper)
                    if match:
                        bag_candidates.append((float(match.group()), existing_uom.id))

            uom_package_id = False
            if bag_candidates:
                bag_candidates.sort(key=lambda x: x[0])
                uom_package_id = bag_candidates[0][1]

            if not has_valid_conversion or not product_name or not categ_name:
                _logger.warning(
                    "Produk SAP %s dilewati karena konversi tidak valid atau "
                    "MAKTX/MTBEZ kosong",
                    matnr,
                )
                continue

            category = category_map.get(categ_name)
            categ_vals = {
                'name': categ_name,
                'packaging_reserve_method': 'full',
            }

            if not category:
                category = category_model.create(categ_vals)
                category_map[categ_name] = category
            else:
                if self._needs_update(category, categ_vals):
                    category.write(categ_vals)

            vals = {
                'name': product_name,
                'uom_id': uom_package_id if uom_package_id else uom_kg.id,
                'categ_id': category.id,
                'weight': weight,
                'default_code': matnr,
                'barcode': matnr,
                'uom_package_id': uom_package_id,
                'uom_ids': [(6, 0, uom_ids)],
                'sale_ok': True,
                'purchase_ok': True,
                'sap_sync': True,
                'type': 'consu',
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
                template = existing_pp.product_tmpl_id
                if self._needs_update(template, vals):
                    write_map[template.id] = vals
            else:
                create_key = (matnr, company.id)
                create_vals = dict(vals)
                create_vals['company_id'] = company.id
                pending_creates[create_key] = create_vals

        create_products = list(pending_creates.values())

        if create_products:
            self.sudo().create(create_products)
            _logger.info(
                "cron_food_synchronize_sap_product CREATED %s templates",
                len(create_products),
            )

        for pid, vals in write_map.items():
            self.sudo().browse(pid).write(vals)
            
        if write_map:
            _logger.info(
                "cron_food_synchronize_sap_product UPDATED %s templates",
                len(write_map),
            )
            
        return True
