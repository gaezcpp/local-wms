from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
from collections import defaultdict
import logging
import requests
import json
_logger = logging.getLogger(__name__)


class MaintenanceEquipment(models.Model):
    _inherit = "maintenance.equipment"

    equipment_no = fields.Char(string="No. Equipment", readonly=True, default=lambda self: self.env["ir.sequence"].next_by_code("maintenance.equipment.no") or _("New"))
    abc_indc = fields.Char(string="Abc Indc")
    parent_equipment_id = fields.Many2one("maintenance.equipment", string="Superior Equipment")
    product_line_ids = fields.One2many("maintenance.equipment.product.line", "equipment_id", string="Products")
    system_id = fields.Many2one("tagging.system", string="System")
    sub_system_id = fields.Many2one("tagging.subsystem", string="Sub System",)
    sap_equnr = fields.Char(string="SAP Equipment No")
    sap_tplnr = fields.Char(string="SAP Functional Location")

    @api.onchange("system_id", "parent_equipment_id")
    def _onchange_effective_system(self):
        self.sub_system_id = False

    @api.constrains("system_id", "sub_system_id", "company_id", "parent_equipment_id")
    def _check_fl_complete(self):
        for rec in self:
            if rec.env.context.get("skip_fl_complete"):
                continue

            sys = rec.system_id or rec.parent_equipment_id.system_id
            sub = rec.sub_system_id or rec.parent_equipment_id.sub_system_id

            if not (sys or sub):
                continue

            if not sys:
                raise ValidationError(_("System is required when BU is set."))
            if sys and not sub:
                raise ValidationError(_("Sub System is required when System is set."))
            if sub and sys and sub.system_id != sys:
                raise ValidationError(_("Sub System must belong to selected System."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("equipment_no") or vals.get("equipment_no") == "New":
                vals["equipment_no"] = self.env["ir.sequence"].next_by_code("maintenance.equipment.no") or _("New")
        return super().create(vals_list)

    @api.constrains("parent_equipment_id")
    def _check_no_cycle(self):
        for rec in self:
            if not rec.parent_equipment_id:
                continue
            if rec.parent_equipment_id == rec:
                raise ValidationError(_("Superior Equipment cannot be itself."))

            parent = rec.parent_equipment_id
            seen = {rec.id}
            while parent:
                if parent.id in seen:
                    raise ValidationError(_("Circular hierarchy is not allowed."))
                seen.add(parent.id)
                parent = parent.parent_equipment_id

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
            _logger.info(f"CRON {cron_name} NOT SUCCESS")
            return []

        data_list = res.get('data', [])
        _logger.info(f"CRON {cron_name} - TOTAL DATA: {len(data_list)}")
        return data_list
    
    @api.model
    def cron_sync_equipment(self):
        data_list = self._fetch_sap_data(
            config_key='query_equipment_sku_sap',
            cron_name='cron_sync_equipment',
        )
        if not data_list:
            return True
        _logger.info(f"TOTAL DATA cron_sync_equipment: {len(data_list)}")
        
        company_model = self.env['res.company'].sudo()
        equipment_model = self.env['maintenance.equipment'].sudo()
        sub_system_model = self.env['tagging.subsystem'].sudo()
        sparepart_model = self.env['tagging.spare_part'].sudo()
        eq_product_line_model = self.env['maintenance.equipment.product.line'].sudo()
        
        grouped_data = defaultdict(list)
        
        for row in data_list:
            eq_raw = row.get('CODE') or row.get('EQUNR')
            if eq_raw:
                eq_code = str(eq_raw).lstrip('0')
                if eq_code:
                    grouped_data[eq_code].append(row)
        
        processed_codes = set()
        processing_codes = set()
        
        def process_equipment(eq_code):
            if eq_code in processed_codes:
                return
            
            if eq_code in processing_codes:
                _logger.warning(f"Circular dependency detected for Equipment {eq_code}. Skipping parent generation.")
                return
                
            processing_codes.add(eq_code)
            rows = grouped_data[eq_code]
            first = rows[0]
            
            raw_parent = first.get('PARENT') or first.get('HEQUI')
            eq_parent = str(raw_parent).lstrip('0') if raw_parent else False
            
            if eq_parent and eq_parent in grouped_data and eq_parent not in processed_codes:
                process_equipment(eq_parent)
                
            eq_name = (first.get('EQUIPMENT_NAME') or first.get('EQKTX'))
            abc_indc = (first.get('ABC_INDC') or first.get('ABCKZ'))
            werks = (first.get('COMPANY_ID') or first.get('WERKS'))
            tplnr = (first.get('FUNCTIONAL_LOCATION') or first.get('TPLNR'))
            
            company = company_model.search([('company_registry', '=', werks)], limit=1)
            if not company:
                _logger.info(f"cron_sync_equipment COMPANY {werks} SKIPPED for EQ {eq_code}")
                processing_codes.remove(eq_code)
                processed_codes.add(eq_code)
                return
            
            sub_system = sub_system_model.search([('code', '=', tplnr), ('company_id', '=', company.id)], limit=1)
            if not sub_system:
                _logger.info(f"cron_sync_equipment SUB SYSTEM {tplnr} SKIPPED for EQ {eq_code}")
                processing_codes.remove(eq_code)
                processed_codes.add(eq_code)
                return
            
            parent_equip = False
            if eq_parent:
                parent_equip = equipment_model.search([('equipment_no', '=', eq_parent), ('company_id', '=', company.id)], limit=1)
            
            eq = equipment_model.search([('equipment_no', '=', eq_code), ('company_id', '=', company.id)], limit=1)
            vals = {
                'name': eq_name,
                'company_id': company.id,
                'equipment_assign_to': 'other',
                'equipment_no': eq_code,
                'abc_indc': abc_indc,
                'parent_equipment_id': parent_equip.id if parent_equip else False,
                'system_id': sub_system.system_id.id,
                'sub_system_id': sub_system.id,
            }
            
            if not eq:
                vals_create = vals.copy()
                eq = equipment_model.create(vals_create)
                eq.message_post(body=f"Equipment {eq_code} Created from cron")
                _logger.info(f"Equipment Created {eq_code}")
            else:
                if self._needs_update(eq, vals):
                    eq.write(vals)
            
            for row in rows:
                sku_raw = (row.get('SKU') or row.get('IDNRK'))
                if not sku_raw:
                    continue
                
                sku = str(sku_raw).lstrip('0') if sku_raw else False
                sparepart = sparepart_model.search([('sku', '=', sku), ('company_id', '=', company.id)], limit=1)
                if not sparepart:
                    continue
                
                name = (row.get('NAME') or row.get('MAKTG'))
                existing_eq_line = eq_product_line_model.search([
                    ('equipment_id', '=', eq.id),
                    ('spare_part_id', '=', sparepart.id),
                ], limit=1)
                
                vals_line = {
                    'equipment_id': eq.id,
                    'spare_part_id': sparepart.id,
                    'sku': sku,
                    'qty': 1,
                    'note': name,
                }
                
                if existing_eq_line:
                    if self._needs_update(existing_eq_line, vals_line):
                        existing_eq_line.write({
                            'spare_part_id': sparepart.id,
                            'note': name,
                        })
                else:
                    eq_product_line_model.create(vals_line)

            _logger.info(f"EQUIP {eq_code} total line {len(rows)}")
            
            processing_codes.remove(eq_code)
            processed_codes.add(eq_code)

        for eq_code in list(grouped_data.keys()):
            process_equipment(eq_code)
            
            
    # NYEBOKIN ORANG GILA SYNCHRONIZE MASA SAMPE 700+ LINES ANJ
    # def _get_sap_endpoint(self):
    #     ip_sap_rfc = self.env['ir.config_parameter'].sudo().get_param('ip_sap_rfc')
    #     if not ip_sap_rfc:
    #         ip_sap_rfc = self.env['ir.config_parameter'].sudo().get_param('ip_sap_rfc_tagging')
    #     url = f"{str(ip_sap_rfc)}/api/v1/zfm-query-data"
    #     return url

    # def _get_sap_api_key(self):
    #     key = self.env["ir.config_parameter"].sudo().get_param("x_i_api_key")
    #     if not key:
    #         key = self.env["ir.config_parameter"].sudo().get_param("x_i_api_key_tagging")
    #     return key

    # def _post_sap_query(self, query: str, mod: str = ""):
    #     url = (self._get_sap_endpoint() or "").strip()
    #     if not url:
    #         raise UserError(_("SAP endpoint is not configured (tagging_system.sap.endpoint)."))

    #     headers = {
    #         "Accept": "application/json",
    #         "Content-Type": "application/json",
    #         "x-i-api-key": self._get_sap_api_key(),
    #     }
    #     payload = {"I_QUERY": query, "I_MOD": mod or ""}

    #     try:
    #         resp = requests.post(url, headers=headers, json=payload, timeout=60)
    #     except requests.RequestException as e:
    #         _logger.exception("SAP API request failed. url=%s", url)
    #         raise UserError(_("SAP API request failed: %s") % str(e))

    #     if resp.status_code >= 400:
    #         raise UserError(_("SAP API error %s: %s") % (resp.status_code, resp.text))

    #     return resp.json()

    # def _extract_rows(self, sap_response):
    #     for key in ("data", "T_DATA", "results", "rows"):
    #         if isinstance(sap_response, dict) and key in sap_response and isinstance(sap_response[key], list):
    #             return sap_response[key]
    #     if isinstance(sap_response, list):
    #         return sap_response
    #     return []

    # def _normalize_row_keys(self, row: dict) -> dict:
    #     return {(k or "").lower(): v for k, v in (row or {}).items()}

    # def _normalize_tplnr(self, tplnr: str) -> str:
    #     tplnr = str(tplnr or "").strip()
    #     if not tplnr:
    #         return ""
    #     tplnr = tplnr.replace(" - ", "-").replace(" -", "-").replace("- ", "-")
    #     tplnr = tplnr.replace(" / ", "/").replace(" /", "/").replace("/ ", "/")
    #     while "--" in tplnr:
    #         tplnr = tplnr.replace("--", "-")
    #     return tplnr

    # # ✅ Sistem + Subsystem FULL dari tplnr
    # def _extract_system_and_subsystem_from_tplnr(self, tplnr: str):
    #     """
    #     Dari SAP: CPB-LPG-01-02-001
    #     Master:
    #       - tagging.system.code     = CPB-LPG-01-02
    #       - tagging.subsystem.code  = CPB-LPG-01-02-001  (FULL)
    #     """
    #     tplnr = self._normalize_tplnr(tplnr)
    #     if not tplnr:
    #         return ("", "")

    #     if "-" in tplnr:
    #         parts = [p.strip() for p in tplnr.split("-") if p.strip()]
    #         joiner = "-"
    #     elif "/" in tplnr:
    #         parts = [p.strip() for p in tplnr.split("/") if p.strip()]
    #         joiner = "/"
    #     else:
    #         return ("", "")

    #     if len(parts) < 5:
    #         return ("", "")

    #     system_code = joiner.join(parts[:4])
    #     subsystem_code = joiner.join(parts[:5])
    #     return (system_code, subsystem_code)

    # def _find_company(self, werks, name1):
    #     Company = self.env["res.company"].sudo()
    #     werks = str(werks or "").strip()

    #     if werks and "company_registry" in Company._fields:
    #         comp = Company.search([("company_registry", "=", werks)], limit=1)
    #         if comp:
    #             return comp
    #     return self.env.company

    # def _upsert_equipment_from_row(self, row, cache):
    #     equnr = row.get("code").lstrip('0')
    #     if not equnr:
    #         return
    #     company = self._find_company(row.get("company_id"), row.get("company_name"))
    #     Equipment = (
    #         self.env["maintenance.equipment"]
    #         .sudo()
    #         .with_context(allowed_company_ids=[company.id], skip_fl_complete=True)
    #         .with_company(company)
    #     )
    #     equipment_name = str(row.get("equipment_name") or "").strip()
    #     display_name = equipment_name or equnr
    #     tplnr = self._normalize_tplnr(row.get("functional_location") or "")
    #     vals = {
    #         "equipment_no": equnr.lstrip('0'),
    #         "sap_equnr": equnr,
    #         "sap_tplnr": tplnr or False,
    #         "abc_indc": str(row.get("abc_indc") or "").strip() or False,
    #         "name": display_name,
    #         "company_id": company.id,
    #         "last_sync_at": fields.Datetime.now(),
    #         "sync_status": "success",
    #         "sync_message": False,
    #     }

    #     system_code, subsystem_code = self._extract_system_and_subsystem_from_tplnr(tplnr)
    #     if system_code:
    #         System = (
    #             self.env["tagging.system"]
    #             .sudo()
    #             .with_context(allowed_company_ids=[company.id])
    #             .with_company(company)
    #         )

    #         domain_sys = [("code", "=ilike", system_code)]
    #         if "company_id" in System._fields:
    #             domain_sys = [("company_id", "=", company.id)] + domain_sys
    #         elif "plant_id" in System._fields:
    #             domain_sys = [("plant_id", "=", company.id)] + domain_sys

    #         sys_rec = System.search(domain_sys, limit=1)
    #         if not sys_rec:
    #             domain_like = domain_sys[:-1] + [("code", "=like", system_code + "%")]
    #             sys_rec = System.search(domain_like, limit=1)

    #         if sys_rec:
    #             vals["system_id"] = sys_rec.id
    #             if subsystem_code:
    #                 SubSystem = (
    #                     self.env["tagging.subsystem"]
    #                     .sudo()
    #                     .with_context(allowed_company_ids=[company.id])
    #                     .with_company(company)
    #                 )
    #                 sub_rec = SubSystem.search([
    #                     ("system_id", "=", sys_rec.id),
    #                     ("code", "=ilike", subsystem_code)
    #                 ],limit=1)

    #                 if sub_rec:
    #                     vals["sub_system_id"] = sub_rec.id
    #                 else:
    #                     _logger.warning(
    #                         "SUBSYSTEM NOT FOUND subsystem_code=%s system=%s tplnr=%s company=%s",
    #                         subsystem_code,
    #                         sys_rec.code,
    #                         tplnr,
    #                         company.display_name,
    #                     )
    #         else:
    #             _logger.warning(
    #                 "SYSTEM NOT FOUND system_code=%s tplnr=%s company=%s",
    #                 system_code,
    #                 tplnr,
    #                 company.display_name,
    #             )
    #     else:
    #         _logger.warning("SYSTEM CODE EMPTY tplnr=%s", tplnr)

    #     cache_key = (company.id, equnr)
    #     rec = cache.get(cache_key)
    #     if not rec:
    #         rec = Equipment.search(
    #             [
    #                 ("company_id", "=", company.id),
    #                 "|",
    #                 ("sap_equnr", "=", equnr),
    #                 ("equipment_no", "=", equnr),
    #             ],
    #             limit=1,
    #         )
    #     if rec:
    #         rec.write(vals)
    #     else:
    #         rec = Equipment.create(vals)

    #     cache[cache_key] = rec
    #     self._upsert_equipment_spare_part_line(rec, row, company)
    #     parent_equnr = row.get("parent").lstrip('0')
    #     if parent_equnr and parent_equnr != equnr:
    #         cache.setdefault("_parent_map", {})[(company.id, equnr)] = parent_equnr
    
    # def _find_or_create_spare_part_from_row(self, row, company):
    #     sku = str(row.get("sku") or "").strip()
    #     spare_name = str(row.get("name") or "").strip()

    #     if not sku and not spare_name:
    #         return False

    #     SparePart = (
    #         self.env["tagging.spare_part"]
    #         .sudo()
    #         .with_context(allowed_company_ids=[company.id])
    #         .with_company(company)
    #     )
        
    #     spare_part = False

    #     search_domains = []
    #     if sku:
    #         if "company_id" in SparePart._fields:
    #             search_domains.append([("company_id", "=", company.id), ("sku", "=ilike", sku)])
    #         search_domains.append([("sku", "=ilike", sku)])

    #     if spare_name:
    #         if "name" in SparePart._fields:
    #             if "company_id" in SparePart._fields:
    #                 search_domains.append([("company_id", "=", company.id), ("name", "=ilike", spare_name)])
    #             search_domains.append([("name", "=ilike", spare_name)])

    #     for domain in search_domains:
    #         spare_part = SparePart.search(domain, limit=1)
    #         if spare_part:
    #             _logger.warning("SPAREPART FOUND domain=%s id=%s", domain, spare_part.id)
    #             return spare_part

    #     spare_vals = {
    #         "name": spare_name or False,
    #         "sku": sku or False,
    #     }
    #     if "company_id" in SparePart._fields:
    #         spare_vals["company_id"] = company.id

    #     spare_part = SparePart.create(spare_vals)

    #     _logger.warning(
    #         "SPAREPART AUTO-CREATED id=%s name=%s sku=%s product_id=%s company=%s",
    #         spare_part.id,
    #         spare_vals.get("name"),
    #         spare_vals.get("sku"),
    #         company.display_name,
    #     )

    #     return spare_part
            
    # def _upsert_equipment_spare_part_line(self, equipment, row, company):
    #     sku = str(row.get("sku") or "").strip()
    #     spare_name = str(row.get("name") or "").strip()

    #     if not sku and not spare_name:
    #         _logger.warning("SPAREPART SKIP empty sku/name equipment=%s", equipment.display_name)
    #         return

    #     ProductLine = (
    #         self.env["maintenance.equipment.product.line"]
    #         .sudo()
    #         .with_context(allowed_company_ids=[company.id])
    #         .with_company(company)
    #     )

    #     spare_part = self._find_or_create_spare_part_from_row(row, company)
    #     if not spare_part:
    #         _logger.warning(
    #             "SPAREPART FAILED TO RESOLVE sku=%s name=%s equipment=%s company=%s",
    #             sku, spare_name, equipment.display_name, company.display_name
    #         )
    #         return

    #     line = ProductLine.search(
    #         [
    #             ("equipment_id", "=", equipment.id),
    #             ("spare_part_id", "=", spare_part.id),
    #         ],
    #         limit=1,
    #     )

    #     vals = {
    #         "equipment_id": equipment.id,
    #         "spare_part_id": spare_part.id,
    #         "qty": 1.0,
    #     }

    #     if spare_name and spare_part.product_id and spare_name != spare_part.product_id.display_name:
    #         vals["note"] = spare_name

    #     if line:
    #         line.write(vals)
    #         _logger.warning(
    #             "SPAREPART LINE UPDATED equipment=%s line_id=%s spare_part_id=%s",
    #             equipment.display_name, line.id, spare_part.id
    #         )
    #     else:
    #         line = ProductLine.create(vals)
    #         _logger.warning(
    #             "SPAREPART LINE CREATED equipment=%s line_id=%s spare_part_id=%s",
    #             equipment.display_name, line.id, spare_part.id
    #         )
            
        
    # def _apply_parent_links(self, cache: dict):
    #     parent_map = cache.get("_parent_map") or {}
    #     if not parent_map:
    #         _logger.warning("PARENT LINK PASS: empty parent_map")
    #         return

    #     EquipmentBase = self.env["maintenance.equipment"].sudo().with_context(active_test=False)
    #     _logger.warning("PARENT LINK PASS SIZE=%s", len(parent_map))

    #     for (company_id, child_equnr), parent_equnr in parent_map.items():
    #         try:
    #             child_equnr = child_equnr.lstrip('0')
    #             parent_equnr = parent_equnr.lstrip('0')
    #             if not child_equnr or not parent_equnr:
    #                 _logger.warning(
    #                     "PARENT SKIP: empty equnr child=%s parent=%s company_id=%s",
    #                     child_equnr,
    #                     parent_equnr,
    #                     company_id,
    #                 )
    #                 continue
    #             if child_equnr == parent_equnr:
    #                 _logger.warning("PARENT SKIP: same equnr child=parent=%s company_id=%s", child_equnr, company_id)
    #                 continue

    #             company = self.env["res.company"].sudo().browse(company_id)
    #             if not company.exists():
    #                 _logger.warning("PARENT SKIP: company not found company_id=%s", company_id)
    #                 continue

    #             Equipment = (
    #                 EquipmentBase.with_context(
    #                     allowed_company_ids=[company.id], active_test=False
    #                 ).with_company(company)
    #             )

    #             child = Equipment.search(
    #                 [
    #                     ("company_id", "=", company.id),
    #                     "|",
    #                     ("sap_equnr", "=", child_equnr),
    #                     ("equipment_no", "=", child_equnr),
    #                 ],
    #                 limit=1,
    #             )
    #             if not child:
    #                 _logger.warning("PARENT SKIP: child not found child=%s company=%s", child_equnr, company.display_name)
    #                 continue

    #             parent = Equipment.search(
    #                 [
    #                     ("company_id", "=", company.id),
    #                     "|",
    #                     ("sap_equnr", "=", parent_equnr),
    #                     ("equipment_no", "=", parent_equnr),
    #                 ],
    #                 limit=1,
    #             )
    #             if not parent:
    #                 _logger.warning(
    #                     "PARENT SKIP: parent not found child=%s parent=%s company=%s",
    #                     child_equnr,
    #                     parent_equnr,
    #                     company.display_name,
    #                 )
    #                 continue

    #             if child.parent_equipment_id and child.parent_equipment_id.id == parent.id:
    #                 _logger.info(
    #                     "PARENT OK (already) child=%s(id=%s) -> parent=%s(id=%s) company=%s",
    #                     child_equnr,
    #                     child.id,
    #                     parent_equnr,
    #                     parent.id,
    #                     company.display_name,
    #                 )
    #                 continue

    #             if child.id == parent.id:
    #                 _logger.warning("PARENT SKIP: child==parent id=%s equnr=%s company=%s", child.id, child_equnr, company.display_name)
    #                 continue

    #             if parent.parent_equipment_id and parent.parent_equipment_id.id == child.id:
    #                 _logger.warning("PARENT SKIP: circular link child=%s parent=%s company=%s", child_equnr, parent_equnr, company.display_name)
    #                 continue

    #             child_ctx = child.sudo().with_company(company).with_context(
    #                 allowed_company_ids=[company.id], active_test=False
    #             )
    #             child_ctx.write({"parent_equipment_id": parent.id})

    #             _logger.warning(
    #                 "PARENT LINKED OK child=%s(id=%s) -> parent=%s(id=%s) company=%s",
    #                 child_equnr,
    #                 child.id,
    #                 parent_equnr,
    #                 parent.id,
    #                 company.display_name,
    #             )

    #         except Exception as e:
    #             _logger.exception(
    #                 "PARENT LINK FAILED child=%s parent=%s company_id=%s err=%s",
    #                 child_equnr,
    #                 parent_equnr,
    #                 company_id,
    #                 str(e),
    #             )
    #             continue

    # def cron_sync_equipment(self):
    #     query = self.env['ir.config_parameter'].sudo().get_param('query_equipment_sku_sap')
    #     try:
    #         _logger.warning("SAP equipment query: %s", query)
    #         sap = self._post_sap_query(query, mod="")
    #         rows = self._extract_rows(sap)
    #         if not rows:
    #             _logger.warning("SAP Equipment sync: no rows returned.")
    #             return True

    #         rows = [self._normalize_row_keys(r) for r in rows]
    #         cache = {}
    #         ok = True
    #         for row in rows:
    #             try:
    #                 _logger.warning(
    #                     "UPSERT EQUNR=%s EQUIPMENT_NAME=%s COMPANY_ID=%s PARENT=%s FL=%s",
    #                     row.get("code").lstrip('0'),
    #                     row.get("equipment_name"),
    #                     row.get("company_id"),
    #                     row.get("parent"),
    #                     row.get("functional_location"),
    #                 )
    #                 self._upsert_equipment_from_row(row, cache)
    #             except Exception:
    #                 ok = False
    #                 _logger.exception("UPSERT FAILED EQUNR=%s ROW=%s", row.get("code").lstrip('0'), row)

    #         self._apply_parent_links(cache)
    #         _logger.info("SAP Equipment Sync completed. Rows=%s ok=%s", len(rows), ok)
    #         return ok
    #     except Exception:
    #         _logger.exception("SAP Equipment sync failed")
    #         return False