import requests
import json
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class TaggingSystem(models.Model):
    _name = "tagging.system"
    _description = "Tagging System"
    _order = "name asc"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)

    company_id = fields.Many2one("res.company", string="Plant", required=True, default=lambda self: self.env.company)
    # =========================
    # INTEGRATION AUDIT FIELDS
    # =========================
    sap_tplnr = fields.Char(string="SAP Functional Location Code")  # biasanya sama dengan code
    sap_werks = fields.Char(string="SAP Plant Code (WERKS)")
    last_sync_at = fields.Datetime(string="Last Sync At", readonly=True)
    sync_status = fields.Selection(
        [("success", "Success"), ("failed", "Failed")],
        string="Sync Status",
        readonly=True,
    )
    sync_message = fields.Text(string="Sync Message", readonly=True)
    sap_synchronize = fields.Boolean(string="SAP Synchronize")
#     _sql_constraints = [
#     (
#         "tagging_system_code_company_uniq",
#         "unique(code, company_id)",
#         "System code must be unique per Plant.",
#     ),
# ]


class TaggingSubSystem(models.Model):
    _name = "tagging.subsystem"
    _description = "Tagging Sub System"
    _order = "name asc"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    system_id = fields.Many2one("tagging.system", required=True, ondelete="cascade")
    active = fields.Boolean(default=True)
       # =========================
    # INTEGRATION AUDIT FIELDS
    # =========================
    sap_tplnr = fields.Char(string="SAP Functional Location Code")  # biasanya sama dengan code
    sap_werks = fields.Char(string="SAP Plant Code (WERKS)")
    last_sync_at = fields.Datetime(string="Last Sync At", readonly=True)
    sync_status = fields.Selection(
        [("success", "Success"), ("failed", "Failed")],
        string="Sync Status",
        readonly=True,
    )
    sync_message = fields.Text(string="Sync Message", readonly=True)
    sap_synchronize = fields.Boolean(string="SAP Synchronize", readonly=True)
    company_id = fields.Many2one("res.company", string="Plant", required=True, default=lambda self: self.env.company)
    abc_indicator = fields.Char(string="ABC Indicator")
    
    # _sql_constraints = [
    #     ("tagging_subsystem_code_per_system_uniq",
    #      "unique(system_id, code)",
    #      "Sub System code must be unique per System."),
    # ]


class TaggingMachineUnit(models.Model):
    _name = "tagging.machine_unit"
    _description = "Tagging Unit Mesin"
    _order = "name asc"

    name = fields.Char(required=True)
    subsystem_id = fields.Many2one("tagging.subsystem", required=True, ondelete="cascade")
    bu_id = fields.Many2one("tagging.bu", required=True, ondelete="restrict")
    active = fields.Boolean(default=True)


class TaggingMachinePart(models.Model):
    _name = "tagging.machine_part"
    _description = "Tagging Bagian Mesin"
    _order = "name asc"

    name = fields.Char(required=True)
    unit_id = fields.Many2one("tagging.machine_unit", required=True, ondelete="cascade")
    active = fields.Boolean(default=True)


class TaggingSparePart(models.Model):
    _name = "tagging.spare_part"
    _description = "Tagging Spare Part Master"
    _order = "name asc"

    name = fields.Char(required=True)
    specification = fields.Text(string="Spesifikasi Spare Part")
    sku = fields.Char(string="SKU")
    bu_id = fields.Many2one("tagging.bu", string="BU", ondelete="restrict")
    company_id = fields.Many2one(
        "res.company",
        string="Plant",
        ondelete="restrict",
        required=True,
        default=lambda self: self.env.company,
    )

    active = fields.Boolean(default=True)

    product_id = fields.Many2one(
        "product.product",
        string="Product",
        required=False,
        ondelete="restrict",
    )

class TaggingMachineBOM(models.Model):
    """
    1 record = 1 baris Excel:
    sistem | sub_sistem | unit_mesin | bagian_mesin | spare_part | spesifikasi | sku | bu
    """
    _name = "tagging.machine_bom"
    _description = "Equipment Tree / BOM"
    _order = "system_id, subsystem_id, unit_id, part_id, spare_part_id"

    system_id = fields.Many2one("tagging.system", required=True, ondelete="restrict")

    subsystem_id = fields.Many2one(
        "tagging.subsystem",
        required=True,
        ondelete="restrict",
        domain="[('system_id', '=', system_id)]",
    )

    unit_id = fields.Many2one(
        "tagging.machine_unit",
        required=True,
        ondelete="restrict",
        domain="[('subsystem_id', '=', subsystem_id)]",
    )

    part_id = fields.Many2one(
        "tagging.machine_part",
        required=True,
        ondelete="restrict",
        domain="[('unit_id', '=', unit_id)]",
    )

    spare_part_id = fields.Many2one("tagging.spare_part", required=True, ondelete="restrict")

    # snapshot dari spare part master (auto keisi saat pilih spare_part_id)
    specification = fields.Text(string="Spesifikasi (Snapshot)")
    sku = fields.Char(string="SKU (Snapshot)")
    bu_id = fields.Many2one("tagging.bu", string="BU (Snapshot)", ondelete="restrict")

    active = fields.Boolean(default=True)
    display_name = fields.Char(compute="_compute_display_name", store=True)

    # ---------- Helpers ----------
    def _prepare_snapshot_from_spare_part(self, spare_part):
        """Return dict snapshot berdasarkan spare part"""
        return {
            "specification": spare_part.specification or False,
            "sku": spare_part.sku or False,
            "bu_id": spare_part.bu_id.id if spare_part.bu_id else False,
        }

    # ---------- UI: onchange ----------
    @api.onchange("spare_part_id")
    def _onchange_spare_part_id(self):
        for rec in self:
            sp = rec.spare_part_id
            if sp:
                snap = rec._prepare_snapshot_from_spare_part(sp)
                rec.specification = snap["specification"]
                rec.sku = snap["sku"]
                rec.bu_id = snap["bu_id"]
            else:
                rec.specification = False
                rec.sku = False
                rec.bu_id = False

    
    @api.depends("system_id", "subsystem_id", "unit_id", "part_id", "spare_part_id")
    def _compute_display_name(self):
        for rec in self:
            parts = [
                rec.system_id.name if rec.system_id else "",
                rec.subsystem_id.name if rec.subsystem_id else "",
                rec.unit_id.name if rec.unit_id else "",
                rec.part_id.name if rec.part_id else "",
                rec.spare_part_id.name if rec.spare_part_id else "",
            ]
            rec.display_name = " / ".join([p for p in parts if p])
            
    # ---------- Backend: create/write (import/API aman) ----------
    @api.model_create_multi
    def create(self, vals_list):
        sp_model = self.env["tagging.spare_part"].sudo()
        for vals in vals_list:
            sp_id = vals.get("spare_part_id")
            if not sp_id:
                continue

            sp = sp_model.browse(sp_id)
            snap = {
                "specification": sp.specification or False,
                "sku": sp.sku or False,
                "bu_id": sp.bu_id.id if sp.bu_id else False,
            }

            # isi snapshot hanya kalau belum dikirim dari luar (biar bisa override saat import)
            vals.setdefault("specification", snap["specification"])
            vals.setdefault("sku", snap["sku"])
            vals.setdefault("bu_id", snap["bu_id"])

        return super().create(vals_list)

    
    @api.onchange("system_id")
    def _onchange_system_id(self):
        for rec in self:
            rec.subsystem_id = False
            rec.unit_id = False
            rec.part_id = False

    @api.onchange("subsystem_id")
    def _onchange_subsystem_id(self):
        for rec in self:
            rec.unit_id = False
            rec.part_id = False

    @api.onchange("unit_id")
    def _onchange_unit_id(self):
        for rec in self:
            rec.part_id = False
        
        
    def write(self, vals):
        res = super().write(vals)

        # kalau spare_part_id berubah, update snapshot (tapi jangan timpa kalau user sengaja isi snapshot via vals)
        if "spare_part_id" in vals:
            changed_to = vals.get("spare_part_id")
            if changed_to:
                sp = self.env["tagging.spare_part"].sudo().browse(changed_to)
                snap = self._prepare_snapshot_from_spare_part(sp)

                for rec in self:
                    updates = {}
                    if "specification" not in vals:
                        updates["specification"] = snap["specification"]
                    if "sku" not in vals:
                        updates["sku"] = snap["sku"]
                    if "bu_id" not in vals:
                        updates["bu_id"] = snap["bu_id"]

                    if updates:
                        super(TaggingMachineBOM, rec).write(updates)

        return res



class TaggingSapSyncService(models.AbstractModel):
    _name = "tagging.sap.sync.service"
    _description = "SAP → Odoo Sync Service (Functional Location)"
    
    #### FIXING, TUNNING & CLEANSING CODE ####
    
    @api.model
    def cron_synchronize_sap_functional_location(self):
        icp = self.env['ir.config_parameter'].sudo()
        x_i_api_key = icp.get_param('x_i_api_key') or icp.get_param('x_i_api_key_tagging')
        ip_sap_rfc = icp.get_param('ip_sap_rfc') or icp.get_param('ip_sap_rfc_tagging')
        query_funcloc_sap = icp.get_param('query_funcloc_sap')

        if not query_funcloc_sap:
            raise ValidationError("query_funcloc_sap belum disetting!")

        headers = {
            "x-i-api-key": str(x_i_api_key),
            "Content-Type": "application/json"
        }

        url = f"{ip_sap_rfc}/api/v1/zfm-query-data"
        body = {
            "I_QUERY": str(query_funcloc_sap),
            "I_MOD": "CRON cron_synchronize_sap_functional_location"
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

        system_model = self.env['tagging.system'].sudo()
        subsystem_model = self.env['tagging.subsystem'].sudo()
        company_model = self.env['res.company'].sudo()

        for data in data_list:
            tplnr = data.get('TPLNR') or ''
            pltxu = data.get('PLTXU') or ''
            tplma = data.get('TPLMA') or ''
            eqfnr = (data.get('EQFNR') or '').upper()
            abckz = data.get('ABCKZ') or ''
            company_registry = data.get('SWERK') or ''
            
            if not company_registry:
                continue
            company_id = company_model.search([
                ('company_registry', '=', company_registry),
                ('sync_pm', '=', True)
            ], limit=1)
            if not company_id:
                continue
            
            if eqfnr != 'SUB':
                existing_system = system_model.search([
                    ('code', '=', tplnr),
                    ('company_id', '=', company_id.id)
                ], limit=1)
                vals = {
                    'company_id': company_id.id,
                    'name': pltxu,
                    'code': tplnr,
                    'active': True,
                    'sap_synchronize': True,
                    'last_sync_at': fields.Datetime.now(),
                }
                if existing_system:
                    existing_system.write(vals)
                else:
                    system_model.create(vals)
            else:
                system_id = system_model.search([
                    ('code', '=', tplma),
                    ('company_id', '=', company_id.id)
                ], limit=1)
                if not system_id:
                    continue

                existing_subsystem = subsystem_model.search([
                    ('code', '=', tplnr),
                    ('system_id', '=', system_id.id),
                    ('company_id', '=', company_id.id)
                ], limit=1)
                vals = {
                    'name': pltxu,
                    'system_id': system_id.id,
                    'sap_tplnr': tplnr,
                    'last_sync_at': fields.Datetime.now(),
                    'sap_synchronize': True,
                    'code': tplnr,
                    'active': True,
                    'sap_werks': company_id.company_registry,
                    'abc_indicator': abckz,
                    'company_id': company_id.id,
                }
                if existing_subsystem:
                    existing_subsystem.write(vals)
                else:
                    subsystem_model.create(vals)

    #### FIXING, TUNNING & CLEANSING CODE ####

    # -------------------------
    # Config helpers
    # -------------------------
    def _get_sap_endpoint(self):
        # GAEZ Benerin biar ga bingung confignya
        ip_sap_rfc = self.env['ir.config_parameter'].sudo().get_param('ip_sap_rfc')
        if not ip_sap_rfc:
            ip_sap_rfc = self.env['ir.config_parameter'].sudo().get_param('ip_sap_rfc_tagging')
        url = f"{str(ip_sap_rfc)}/api/v1/zfm-query-data"
        return url
        # return self.env["ir.config_parameter"].sudo().get_param(
        #     "tagging_system.sap.endpoint",
        #     default="https://saprfc-dev.cpp.co.id/api/v1/zfm-query-data"
        # )
    
    def _normalize_row_keys(self, row: dict) -> dict:
        return { (k or "").lower(): v for k, v in (row or {}).items() }

    def action_sync_functional_location_test(self):
        """Manual test: show popup success/failed."""
        self.ensure_one()
        try:
            res = self.cron_sync_functional_location()  # pakai logic cron yang sudah ada
            # kalau cron kamu return dict/summary, boleh masukin ke message
            msg = "Functional Location sync finished."
            if isinstance(res, dict):
                msg = res.get("message") or msg

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "SAP Sync",
                    "message": msg,
                    "type": "success",
                    "sticky": False,
                },
            }
        except Exception as e:
            _logger.exception("SAP sync functional location failed (manual test)")
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "SAP Sync Failed",
                    "message": str(e),
                    "type": "danger",
                    "sticky": True,
                },
            }
            
    def _get_sap_api_key(self):
        # GAEZ Benerin biar ga bingung confignya
        key = self.env["ir.config_parameter"].sudo().get_param("x_i_api_key")
        if not key:
            key = self.env["ir.config_parameter"].sudo().get_param("x_i_api_key_tagging")
            # raise UserError(_("SAP API key is not configured (x_i_api_key)."))
        return key
        # key = self.env["ir.config_parameter"].sudo().get_param("tagging_system.sap.api_key")
        # if not key:
        #     raise UserError(_("SAP API key is not configured (tagging_system.sap.api_key)."))
        # return key

    def _post_sap_query(self, query: str, mod: str = ""):
        """
        Call SAP RFC API that accepts:
        {
          "I_QUERY": "...",
          "I_MOD": ""
        }
        """
        url = self._get_sap_endpoint()
        api_key = self._get_sap_api_key()

        headers = {
            "Content-Type": "application/json",
            "x-i-api-key": api_key,
        }
        payload = {"I_QUERY": query, "I_MOD": mod or ""}

        # timeout penting biar cron tidak ngegantung
        resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=60)
        if resp.status_code >= 400:
            raise UserError(_("SAP API error %s: %s") % (resp.status_code, resp.text))

        data = resp.json()
        return data

    # -------------------------
    # Parsing helper (sesuaikan dengan bentuk response API kamu)
    # -------------------------
    def _extract_rows(self, sap_response):
        """
        Kamu perlu sesuaikan ini dengan format response dari saprfc-dev.
        Umumnya API query akan return list rows di key tertentu.
        Contoh kemungkinan:
          - sap_response["data"]
          - sap_response["T_DATA"]
          - sap_response["results"]
        """
        for key in ("data", "T_DATA", "results", "rows"):
            if isinstance(sap_response, dict) and key in sap_response and isinstance(sap_response[key], list):
                return sap_response[key]
        # fallback: kalau response sudah list
        if isinstance(sap_response, list):
            return sap_response
        return []

    def _find_company_from_sap(self, company_id: str, company_name: str):
        Company = self.env["res.company"].sudo()
        company_id = (company_id or "").strip()
        company_name = (company_name or "").strip()

        # 1) PRIORITAS: match SAP COMPANY_ID -> res.company.company_registry
        if company_id and "company_registry" in Company._fields:
            domain = [("company_registry", "=", company_id)]
            c = Company.search(domain, limit=1)
            if not c and company_id.isdigit():
                c = Company.search([("company_registry", "=", int(company_id))], limit=1)
            if c:
                return c

        # 3) fallback: match name ilike COMPANY_NAME
        # if company_name:
        #     c = Company.search([("name", "=ilike", company_name)], limit=1)
        #     if c:
        #         return c

        # 4) fallback terakhir
        return self.env.company

    # -------------------------
    # Hierarchy filter
    # -------------------------
    def _is_level(self, code: str, level: int):
        """
        Dokumen bilang hierarchy 4 & 5.
        Karena format TPLNR bisa beda-beda tiap company,
        kita buat default rule berbasis segment count pakai '-' (contoh: A-B-C-D => level 4).
        Kalau di SAP kamu pakai fixed length (mis 4-4-4-..), ganti logic ini.
        """
        code = (code or "").strip()
        if not code:
            return False

        # heuristic: segment by '-'
        parts = [p for p in code.split("-") if p]
        if len(parts) >= level:
            return len(parts) == level

        # fallback: kalau tidak pakai '-', coba pakai '/'
        parts = [p for p in code.split("/") if p]
        return len(parts) == level

    # -------------------------
    # UPSERT: tagging.system
    # -------------------------
    def _upsert_system(self, row):
        """
        Row dari query kamu:
        - code
        - name
        - parent
        - company_id      (SAP WERKS / COMPANY_ID, contoh: '1321')
        - company_name    (SAP NAME1, contoh: 'Plant CPB FishFeedmill Lampung')
        - abc_indc
        """
        # normalize
        code = (row.get("code") or "").strip()
        if not code:
            return False

        name = (row.get("name") or "").strip()

        sap_company_id = (row.get("company_id") or "").strip()
        sap_company_name = (row.get("company_name") or "").strip()

        company = self._find_company_from_sap(sap_company_id, sap_company_name)

        # pakai env company yg benar (multi-company safe)
        System = (
            self.env["tagging.system"]
            .with_context(allowed_company_ids=[company.id])
            .with_company(company)
            .sudo()
        )

        existing = System.search([
            ("code", "=", code),
            ("company_id", "=", company.id),
        ], limit=1)

        vals = {
            "name": name or code,
            "code": code,
            "company_id": company.id,
            "sap_tplnr": code,
            "sap_werks": sap_company_id or False,
            "active": True,
            "last_sync_at": fields.Datetime.now(),
            "sync_status": "success",
            "sync_message": False,
        }

        if existing:
            existing.write(vals)
            return existing
        return System.create(vals)

    # -------------------------
    # UPSERT: tagging.subsystem
    # -------------------------
    def _upsert_subsystem(self, row, system_rec):
        # multi-company safe: ikut company dari parent system
        Sub = (
            self.env["tagging.subsystem"]
            .with_context(allowed_company_ids=[system_rec.company_id.id])
            .with_company(system_rec.company_id)
            .sudo()
        )

        code = (row.get("code") or "").strip()          # <-- FULL CODE, contoh: CPB-LPG-01-01-001
        name = (row.get("name") or "").strip()

        # dari API kamu: COMPANY_ID / COMPANY_NAME (setelah normalize jadi company_id/company_name)
        werks = (row.get("company_id") or "").strip()   # <-- FIX
        existing = Sub.search([("system_id", "=", system_rec.id), ("code", "=", code)], limit=1)

        vals = {
            "name": name or code,
            "code": code,               
            "system_id": system_rec.id,
            "sap_tplnr": code,
            "sap_werks": werks or False,
            "active": True,
            "last_sync_at": fields.Datetime.now(),
            "sync_status": "success",
            "sync_message": False,
        }

        if existing:
            existing.write(vals)
            return existing
        return Sub.create(vals)
    
    
    

    # -------------------------
    # MAIN CRON ENTRY
    # -------------------------
    def cron_sync_functional_location(self):
        """
        1 query untuk ambil semua FL + plant
        1) create/update System (level 4)
        2) create/update Subsystem (level 5), relasi ke parent system
        """
        # query = """
        #         select a.tplnr as code, d.pltxu as name, a.tplma as parent ,b.swerk as company_id, c.name1 as company_name, b.abckz as abc_indc from iflot a join iflotx d on a.mandt=d.mandt and a.tplnr=d.tplnr join iloa b on a.mandt=b.mandt and a.tplnr=b.tplnr join t001w c on b.mandt=c.mandt and b.swerk=c.werks where a.tplnr like 'CPB%'
        #         """
        query = self.env['ir.config_parameter'].sudo().get_param('query_funcloc_sap')
        try:
            sap = self._post_sap_query(query, mod="")
            rows = self._extract_rows(sap)
            rows = [self._normalize_row_keys(r) for r in rows]
            if not rows:
                _logger.warning("SAP sync: no rows returned.")
                return True

            # index cache system by (company_id, code)
            system_cache = {}

            for r in rows:
                code = (r.get("code") or "").strip()
                if not code:
                    continue

                # SYSTEM = level 4
                if self._is_level(code, 4):
                    sys_rec = self._upsert_system(r)
                    system_cache[(sys_rec.company_id.id, sys_rec.code)] = sys_rec

            # SUBSYSTEM = level 5, link to parent system
            for r in rows:
                code = (r.get("code") or "").strip()
                if not code or not self._is_level(code, 5):
                    continue

                # parent system code = potong 1 level
                if "-" in code:
                    parent_code = "-".join(code.split("-")[:-1])
                elif "/" in code:
                    parent_code = "/".join(code.split("/")[:-1])
                else:
                    parent_code = ""

                # FIX: pakai company_id/company_name sesuai response API
                sap_company_id = (r.get("company_id") or "").strip()
                sap_company_name = (r.get("company_name") or "").strip()
                company = self._find_company_from_sap(sap_company_id, sap_company_name)

                sys_rec = system_cache.get((company.id, parent_code))
                if not sys_rec:
                    sys_rec = self.env["tagging.system"].sudo().search(
                        [("code", "=", parent_code), ("company_id", "=", company.id)],
                        limit=1
                    )
                if not sys_rec:
                    _logger.warning(
                        "Subsystem %s skipped: parent system %s not found (company=%s)",
                        code, parent_code, company.name
                    )
                    continue

                self._upsert_subsystem(r, sys_rec)

            return True

        except Exception as e:
            _logger.exception("SAP sync functional location failed")
            # optional: catat ke ir.logging / mail.message
            return False

