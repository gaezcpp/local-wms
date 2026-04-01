# -*- coding: utf-8 -*-
import logging
import requests

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


class MaintenanceEquipment(models.Model):
    _inherit = "maintenance.equipment"

    # ==========================================================
    # BASE FIELDS
    # ==========================================================
    equipment_no = fields.Char(
        string="No. Equipment",
        readonly=True,
        copy=False,
        index=True,
        default=lambda self: self.env["ir.sequence"].next_by_code("maintenance.equipment.no") or _("New"),
    )

    abc_indc = fields.Char(string="Abc Indc")

    parent_equipment_id = fields.Many2one(
        "maintenance.equipment",
        string="Superior Equipment",
        ondelete="set null",
    )
    child_equipment_ids = fields.One2many(
        "maintenance.equipment",
        "parent_equipment_id",
        string="Sub Equipments",
    )

    maint_plant_id = fields.Many2one(
        "res.company",
        string="Maint Plant",
        related="company_id",
        store=True,
        readonly=True,
    )

    business_area_id = fields.Many2one(
        "maintenance.business.area",
        string="Business Area",
        ondelete="restrict",
    )

    functional_loc_tagging_id = fields.Many2one(
        "barcode.tagging",
        string="Functional Loc",
        ondelete="set null",
        domain=[("functional_location", "!=", False)],
    )

    product_line_ids = fields.One2many(
        "maintenance.equipment.product.line",
        "equipment_id",
        string="Products",
    )

    child_count = fields.Integer(compute="_compute_child_count", store=True)

    bu_id = fields.Many2one("tagging.bu", string="Business Unit", ondelete="restrict")
    system_id = fields.Many2one("tagging.system", string="System", ondelete="restrict")

    sub_system_id = fields.Many2one(
        "tagging.subsystem",
        string="Sub System",
        ondelete="restrict",
        domain="[('system_id','=',effective_system_id)]",
    )

    effective_system_id = fields.Many2one(
        "tagging.system",
        compute="_compute_effective_system_id",
        store=False,
    )

    functional_location_code = fields.Char(
        string="Functional Location Code",
        compute="_compute_functional_location_code",
        store=True,
    )

    # ==========================================================
    # SAP INTEGRATION AUDIT FIELDS
    # ==========================================================
    sap_equnr = fields.Char(string="SAP Equipment No", index=True)
    sap_tplnr = fields.Char(string="SAP Functional Location", index=True)

    last_sync_at = fields.Datetime(string="Last Sync At", readonly=True)
    sync_status = fields.Selection(
        [("success", "Success"), ("failed", "Failed")],
        string="Sync Status",
        readonly=True,
    )
    sync_message = fields.Text(string="Sync Message", readonly=True)

    # ==========================================================
    # COMPUTES / ONCHANGES / CONSTRAINTS
    # ==========================================================
    @api.depends("system_id", "parent_equipment_id.system_id")
    def _compute_effective_system_id(self):
        for rec in self:
            rec.effective_system_id = rec.system_id or rec.parent_equipment_id.system_id

    @api.onchange("system_id", "parent_equipment_id")
    def _onchange_effective_system(self):
        self.sub_system_id = False

    @api.depends("child_equipment_ids")
    def _compute_child_count(self):
        for rec in self:
            rec.child_count = len(rec.child_equipment_ids)

    # ✅ Clean: FL code tampilkan persis dari SAP (no double)
    @api.depends("sap_tplnr")
    def _compute_functional_location_code(self):
        for rec in self:
            rec.functional_location_code = rec.sap_tplnr or ""

    @api.constrains("bu_id", "system_id", "sub_system_id", "company_id", "parent_equipment_id")
    def _check_fl_complete(self):
        for rec in self:
            if rec.env.context.get("skip_fl_complete"):
                continue

            bu = rec.bu_id or rec.parent_equipment_id.bu_id
            sys = rec.system_id or rec.parent_equipment_id.system_id
            sub = rec.sub_system_id or rec.parent_equipment_id.sub_system_id

            if not (bu or sys or sub):
                continue

            if bu and not sys:
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

    # ==========================================================
    # SAP INTEGRATION HELPERS
    # ==========================================================
    def _get_sap_endpoint(self):
        # GAEZ Benerin biar ga bingung confignya
        ip_sap_rfc = self.env['ir.config_parameter'].sudo().get_param('ip_sap_rfc')
        if not ip_sap_rfc:
            ip_sap_rfc = self.env['ir.config_parameter'].sudo().get_param('ip_sap_rfc_tagging')
        url = f"{str(ip_sap_rfc)}/api/v1/zfm-query-data"
        return url
        # return self.env["ir.config_parameter"].sudo().get_param(
        #     "tagging_system.sap.endpoint",
        #     default="https://saprfc-dev.cpp.co.id/api/v1/zfm-query-data",
        # )

    def _get_sap_api_key(self):
        # GAEZ Benerin biar ga bingung confignya
        key = self.env["ir.config_parameter"].sudo().get_param("x_i_api_key")
        if not key:
            key = self.env["ir.config_parameter"].sudo().get_param("x_i_api_key_tagging")
        return key

    def _post_sap_query(self, query: str, mod: str = ""):
        url = (self._get_sap_endpoint() or "").strip()
        if not url:
            raise UserError(_("SAP endpoint is not configured (tagging_system.sap.endpoint)."))

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-i-api-key": self._get_sap_api_key(),
        }
        payload = {"I_QUERY": query, "I_MOD": mod or ""}

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
        except requests.RequestException as e:
            _logger.exception("SAP API request failed. url=%s", url)
            raise UserError(_("SAP API request failed: %s") % str(e))

        if resp.status_code >= 400:
            raise UserError(_("SAP API error %s: %s") % (resp.status_code, resp.text))

        return resp.json()

    def _extract_rows(self, sap_response):
        for key in ("data", "T_DATA", "results", "rows"):
            if isinstance(sap_response, dict) and key in sap_response and isinstance(sap_response[key], list):
                return sap_response[key]
        if isinstance(sap_response, list):
            return sap_response
        return []

    def _normalize_row_keys(self, row: dict) -> dict:
        return {(k or "").lower(): v for k, v in (row or {}).items()}

    # ---------- Normalizers ----------
    def _norm_equnr(self, v):
        v = str(v or "").strip()
        if v.isdigit():
            return v.zfill(18)
        return v

    def _normalize_tplnr(self, tplnr: str) -> str:
        tplnr = str(tplnr or "").strip()
        if not tplnr:
            return ""
        tplnr = tplnr.replace(" - ", "-").replace(" -", "-").replace("- ", "-")
        tplnr = tplnr.replace(" / ", "/").replace(" /", "/").replace("/ ", "/")
        while "--" in tplnr:
            tplnr = tplnr.replace("--", "-")
        return tplnr

    # ✅ Sistem + Subsystem FULL dari tplnr
    def _extract_system_and_subsystem_from_tplnr(self, tplnr: str):
        """
        Dari SAP: CPB-LPG-01-02-001
        Master:
          - tagging.system.code     = CPB-LPG-01-02
          - tagging.subsystem.code  = CPB-LPG-01-02-001  (FULL)
        """
        tplnr = self._normalize_tplnr(tplnr)
        if not tplnr:
            return ("", "")

        if "-" in tplnr:
            parts = [p.strip() for p in tplnr.split("-") if p.strip()]
            joiner = "-"
        elif "/" in tplnr:
            parts = [p.strip() for p in tplnr.split("/") if p.strip()]
            joiner = "/"
        else:
            return ("", "")

        if len(parts) < 5:
            return ("", "")

        system_code = joiner.join(parts[:4])
        subsystem_code = joiner.join(parts[:5])
        return (system_code, subsystem_code)

    def _find_company(self, werks, name1):
        """
        SAP kirim COMPANY_ID (contoh 1321 / '1321').
        Mapping utama: res.company.company_registry
        """
        Company = self.env["res.company"].sudo()
        werks = str(werks or "").strip()
        name1 = str(name1 or "").strip()

        if werks and "company_registry" in Company._fields:
            comp = Company.search([("company_registry", "=", werks)], limit=1)
            if comp:
                return comp

        # if name1:
        #     comp = Company.search([("name", "=ilike", name1)], limit=1)
        #     if comp:
        #         return comp

        return self.env.company

    # ==========================================================
    # UPSERT EQUIPMENT (SAP → ODOO)
    # ==========================================================
    def _upsert_equipment_from_row(self, row, cache):
        equnr = self._norm_equnr(row.get("code"))
        if not equnr:
            return

        company = self._find_company(row.get("company_id"), row.get("company_name"))

        Equipment = (
            self.env["maintenance.equipment"]
            .sudo()
            .with_context(allowed_company_ids=[company.id], skip_fl_complete=True)
            .with_company(company)
        )

        equipment_name = str(row.get("equipment_name") or "").strip()
        display_name = equipment_name or equnr
        tplnr = self._normalize_tplnr(row.get("functional_location") or "")

        vals = {
            "equipment_no": equnr,
            "sap_equnr": equnr,
            "sap_tplnr": tplnr or False,
            "abc_indc": str(row.get("abc_indc") or "").strip() or False,
            "name": display_name,
            "company_id": company.id,
            "last_sync_at": fields.Datetime.now(),
            "sync_status": "success",
            "sync_message": False,
        }

        # ---- System & Subsystem dari Functional Location ----
        system_code, subsystem_code = self._extract_system_and_subsystem_from_tplnr(tplnr)

        if system_code:
            System = (
                self.env["tagging.system"]
                .sudo()
                .with_context(allowed_company_ids=[company.id])
                .with_company(company)
            )

            domain_sys = [("code", "=ilike", system_code)]
            if "company_id" in System._fields:
                domain_sys = [("company_id", "=", company.id)] + domain_sys
            elif "plant_id" in System._fields:
                domain_sys = [("plant_id", "=", company.id)] + domain_sys

            sys_rec = System.search(domain_sys, limit=1)
            if not sys_rec:
                domain_like = domain_sys[:-1] + [("code", "=like", system_code + "%")]
                sys_rec = System.search(domain_like, limit=1)

            if sys_rec:
                vals["system_id"] = sys_rec.id

                # ✅ Subsystem mapping full, only if system found
                if subsystem_code:
                    SubSystem = (
                        self.env["tagging.subsystem"]
                        .sudo()
                        .with_context(allowed_company_ids=[company.id])
                        .with_company(company)
                    )

                    sub_rec = SubSystem.search(
                        [
                            ("system_id", "=", sys_rec.id),
                            ("code", "=ilike", subsystem_code),
                        ],
                        limit=1,
                    )

                    if sub_rec:
                        vals["sub_system_id"] = sub_rec.id
                    else:
                        _logger.warning(
                            "SUBSYSTEM NOT FOUND subsystem_code=%s system=%s tplnr=%s company=%s",
                            subsystem_code,
                            sys_rec.code,
                            tplnr,
                            company.display_name,
                        )
            else:
                _logger.warning(
                    "SYSTEM NOT FOUND system_code=%s tplnr=%s company=%s",
                    system_code,
                    tplnr,
                    company.display_name,
                )
        else:
            _logger.warning("SYSTEM CODE EMPTY tplnr=%s", tplnr)

        cache_key = (company.id, equnr)

        rec = cache.get(cache_key)
        if not rec:
            rec = Equipment.search(
                [
                    ("company_id", "=", company.id),
                    "|",
                    ("sap_equnr", "=", equnr),
                    ("equipment_no", "=", equnr),
                ],
                limit=1,
            )

        if rec:
            rec.write(vals)
        else:
            rec = Equipment.create(vals)

        cache[cache_key] = rec
        self._upsert_equipment_spare_part_line(rec, row, company)
        parent_equnr = self._norm_equnr(row.get("parent"))
        if parent_equnr and parent_equnr != equnr:
            cache.setdefault("_parent_map", {})[(company.id, equnr)] = parent_equnr
            

    
    def _find_or_create_spare_part_from_row(self, row, company):
        sku = str(row.get("sku") or "").strip()
        spare_name = str(row.get("name") or "").strip()

        if not sku and not spare_name:
            return False

        SparePart = (
            self.env["tagging.spare_part"]
            .sudo()
            .with_context(allowed_company_ids=[company.id])
            .with_company(company)
        )

        Product = (
            self.env["product.product"]
            .sudo()
            .with_context(allowed_company_ids=[company.id])
            .with_company(company)
        )

        spare_part = False

        # 1. cari spare part existing
        search_domains = []
        if sku:
            if "company_id" in SparePart._fields:
                search_domains.append([("company_id", "=", company.id), ("sku", "=ilike", sku)])
            search_domains.append([("sku", "=ilike", sku)])

        if spare_name:
            if "name" in SparePart._fields:
                if "company_id" in SparePart._fields:
                    search_domains.append([("company_id", "=", company.id), ("name", "=ilike", spare_name)])
                search_domains.append([("name", "=ilike", spare_name)])

        for domain in search_domains:
            spare_part = SparePart.search(domain, limit=1)
            if spare_part:
                _logger.warning("SPAREPART FOUND domain=%s id=%s", domain, spare_part.id)
                return spare_part

        # 2. cari / create product.product
        product = False
        if sku:
            product = Product.search([("default_code", "=ilike", sku)], limit=1)

        if not product and spare_name:
            product = Product.search([("name", "=ilike", spare_name)], limit=1)

        if not product:
            product_vals = {
                "name": spare_name or sku,
                "default_code": sku or False,
                "sale_ok": True,
                "purchase_ok": True,
                "type": "consu",
                "company_id": company.id if "company_id" in Product._fields else False,
            }
            product = Product.create(product_vals)
            _logger.warning(
                "PRODUCT AUTO-CREATED id=%s name=%s sku=%s company=%s",
                product.id, product.name, sku, company.display_name
            )

        # 3. create tagging.spare_part
        spare_vals = {
            "name": spare_name or product.display_name or sku,
            "sku": sku or product.default_code or False,
            "product_id": product.id,
        }
        if "company_id" in SparePart._fields:
            spare_vals["company_id"] = company.id

        spare_part = SparePart.create(spare_vals)

        _logger.warning(
            "SPAREPART AUTO-CREATED id=%s name=%s sku=%s product_id=%s company=%s",
            spare_part.id,
            spare_vals.get("name"),
            spare_vals.get("sku"),
            product.id,
            company.display_name,
        )

        return spare_part
            
    def _upsert_equipment_spare_part_line(self, equipment, row, company):
        sku = str(row.get("sku") or "").strip()
        spare_name = str(row.get("name") or "").strip()

        if not sku and not spare_name:
            _logger.warning("SPAREPART SKIP empty sku/name equipment=%s", equipment.display_name)
            return

        ProductLine = (
            self.env["maintenance.equipment.product.line"]
            .sudo()
            .with_context(allowed_company_ids=[company.id])
            .with_company(company)
        )

        spare_part = self._find_or_create_spare_part_from_row(row, company)
        if not spare_part:
            _logger.warning(
                "SPAREPART FAILED TO RESOLVE sku=%s name=%s equipment=%s company=%s",
                sku, spare_name, equipment.display_name, company.display_name
            )
            return

        line = ProductLine.search(
            [
                ("equipment_id", "=", equipment.id),
                ("spare_part_id", "=", spare_part.id),
            ],
            limit=1,
        )

        vals = {
            "equipment_id": equipment.id,
            "spare_part_id": spare_part.id,
            "qty": 1.0,
        }

        if spare_name and spare_part.product_id and spare_name != spare_part.product_id.display_name:
            vals["note"] = spare_name

        if line:
            line.write(vals)
            _logger.warning(
                "SPAREPART LINE UPDATED equipment=%s line_id=%s spare_part_id=%s",
                equipment.display_name, line.id, spare_part.id
            )
        else:
            line = ProductLine.create(vals)
            _logger.warning(
                "SPAREPART LINE CREATED equipment=%s line_id=%s spare_part_id=%s",
                equipment.display_name, line.id, spare_part.id
            )
            
        
    def _apply_parent_links(self, cache: dict):
        parent_map = cache.get("_parent_map") or {}
        if not parent_map:
            _logger.warning("PARENT LINK PASS: empty parent_map")
            return

        EquipmentBase = self.env["maintenance.equipment"].sudo().with_context(active_test=False)
        _logger.warning("PARENT LINK PASS SIZE=%s", len(parent_map))

        for (company_id, child_equnr), parent_equnr in parent_map.items():
            try:
                child_equnr = self._norm_equnr(child_equnr)
                parent_equnr = self._norm_equnr(parent_equnr)

                if not child_equnr or not parent_equnr:
                    _logger.warning(
                        "PARENT SKIP: empty equnr child=%s parent=%s company_id=%s",
                        child_equnr,
                        parent_equnr,
                        company_id,
                    )
                    continue
                if child_equnr == parent_equnr:
                    _logger.warning("PARENT SKIP: same equnr child=parent=%s company_id=%s", child_equnr, company_id)
                    continue

                company = self.env["res.company"].sudo().browse(company_id)
                if not company.exists():
                    _logger.warning("PARENT SKIP: company not found company_id=%s", company_id)
                    continue

                Equipment = (
                    EquipmentBase.with_context(
                        allowed_company_ids=[company.id], active_test=False
                    ).with_company(company)
                )

                child = Equipment.search(
                    [
                        ("company_id", "=", company.id),
                        "|",
                        ("sap_equnr", "=", child_equnr),
                        ("equipment_no", "=", child_equnr),
                    ],
                    limit=1,
                )
                if not child:
                    _logger.warning("PARENT SKIP: child not found child=%s company=%s", child_equnr, company.display_name)
                    continue

                parent = Equipment.search(
                    [
                        ("company_id", "=", company.id),
                        "|",
                        ("sap_equnr", "=", parent_equnr),
                        ("equipment_no", "=", parent_equnr),
                    ],
                    limit=1,
                )
                if not parent:
                    _logger.warning(
                        "PARENT SKIP: parent not found child=%s parent=%s company=%s",
                        child_equnr,
                        parent_equnr,
                        company.display_name,
                    )
                    continue

                if child.parent_equipment_id and child.parent_equipment_id.id == parent.id:
                    _logger.info(
                        "PARENT OK (already) child=%s(id=%s) -> parent=%s(id=%s) company=%s",
                        child_equnr,
                        child.id,
                        parent_equnr,
                        parent.id,
                        company.display_name,
                    )
                    continue

                if child.id == parent.id:
                    _logger.warning("PARENT SKIP: child==parent id=%s equnr=%s company=%s", child.id, child_equnr, company.display_name)
                    continue

                if parent.parent_equipment_id and parent.parent_equipment_id.id == child.id:
                    _logger.warning("PARENT SKIP: circular link child=%s parent=%s company=%s", child_equnr, parent_equnr, company.display_name)
                    continue

                child_ctx = child.sudo().with_company(company).with_context(
                    allowed_company_ids=[company.id], active_test=False
                )
                child_ctx.write({"parent_equipment_id": parent.id})

                _logger.warning(
                    "PARENT LINKED OK child=%s(id=%s) -> parent=%s(id=%s) company=%s",
                    child_equnr,
                    child.id,
                    parent_equnr,
                    parent.id,
                    company.display_name,
                )

            except Exception as e:
                _logger.exception(
                    "PARENT LINK FAILED child=%s parent=%s company_id=%s err=%s",
                    child_equnr,
                    parent_equnr,
                    company_id,
                    str(e),
                )
                continue

    # ==========================================================
    # MAIN CRON ENTRY: Equipment Sync (QUERY TIDAK DIUBAH)
    # ==========================================================
    def cron_sync_equipment(self):
        query = self.env['ir.config_parameter'].sudo().get_param('query_equipment_sku_sap')
        # query = "select a.equnr as code, b.eqktx as equipment_name, c.hequi as parent, e.idnrk as sku, g.maktg as name, f.abckz as abc_indc, h.werks as company_id, h.name1 as company_name, f.tplnr as functional_location from equi a join eqkt b on a.mandt=b.mandt and a.equnr=b.equnr join equz c on a.mandt=c.mandt and a.equnr=c.equnr left join eqst d on a.mandt=d.mandt and a.equnr=d.equnr left join stpo e on d.mandt=e.mandt and d.stlnr=e.stlnr and e.stlty = 'E' join iloa f on c.mandt=f.mandt and c.iloan=f.iloan left join makt g on e.mandt=g.mandt and e.idnrk=g.matnr left join t001w h on f.mandt=h.mandt and f.swerk=h.werks where f.swerk = '1321'"
        try:
            _logger.warning("SAP equipment query: %s", query)

            sap = self._post_sap_query(query, mod="")
            rows = self._extract_rows(sap)
            if not rows:
                _logger.warning("SAP Equipment sync: no rows returned.")
                return True

            rows = [self._normalize_row_keys(r) for r in rows]

            cache = {}
            ok = True

            for row in rows:
                try:
                    _logger.warning(
                        "UPSERT EQUNR=%s EQUIPMENT_NAME=%s COMPANY_ID=%s PARENT=%s FL=%s",
                        row.get("code"),
                        row.get("equipment_name"),
                        row.get("company_id"),
                        row.get("parent"),
                        row.get("functional_location"),
                    )
                    self._upsert_equipment_from_row(row, cache)
                except Exception:
                    ok = False
                    _logger.exception("UPSERT FAILED EQUNR=%s ROW=%s", row.get("code"), row)

            self._apply_parent_links(cache)

            _logger.info("SAP Equipment Sync completed. Rows=%s ok=%s", len(rows), ok)
            return ok

        except Exception:
            _logger.exception("SAP Equipment sync failed")
            return False

    # ==========================================================
    # OPTIONAL: Manual test button (popup notif)
    # ==========================================================
    def action_sync_equipment_test(self):
        try:
            ok = self.cron_sync_equipment()
            if ok:
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "SAP Sync",
                        "message": "Equipment sync finished successfully.",
                        "type": "success",
                        "sticky": False,
                    },
                }
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "SAP Sync",
                    "message": "Equipment sync finished but returned False (check logs).",
                    "type": "warning",
                    "sticky": True,
                    },
                }
        except Exception as e:
            _logger.exception("SAP Equipment sync failed (manual)")
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