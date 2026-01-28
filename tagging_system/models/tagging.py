from odoo import api, fields, models, _
from datetime import timedelta
from odoo.exceptions import UserError


class TaggingRecord(models.Model):
    _name = "tagging.record"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Tagging Record"
    _order = "create_date desc"

    name = fields.Char(string="Ticket", readonly=True, copy=False, default="New")

    user_id = fields.Many2one(
        "res.users",
        string="Created By",
        required=True,
        index=True,
        default=lambda self: self.env.user,
        readonly=True,
    )
    wo_sparepart_ids = fields.One2many(
    "tagging.wo.sparepart",
    "record_id",
    string="WO Spareparts",
    )   

    tagger_name = fields.Char(required=True, tracking=True)

    # =========================
    # MASTER LINKS (WEBSITE FORM)
    # =========================
    barcode_id = fields.Many2one(
        "barcode.tagging",
        string="Barcode",
        index=True,
        ondelete="restrict",
        tracking=True,
    )

    pic_id = fields.Many2one(
        "tagging.pic",
        string="PIC",
        index=True,
        ondelete="restrict",
        tracking=True,
    )

    category_problem_id = fields.Many2one(
        "category.problem",
        string="Category Problem",
        index=True,
        ondelete="restrict",
        tracking=True,
    )

    # snapshot (store) biar gampang search/report
    pic_name = fields.Char(string="PIC Email", related="pic_id.email", store=True, tracking=True)
    problem_category = fields.Char(string="Problem Category", related="category_problem_id.cat_masalah", store=True, tracking=True)

    # =========================
    # EQUIPMENT MASTER (dipilih saat close)
    # =========================
    machine_bom_id = fields.Many2one(
        "tagging.machine_bom",
        string="Equipment (Master)",
        index=True,
        ondelete="restrict",
        tracking=True,
    )

    # =========================
    # SNAPSHOT LOKASI (dari barcode)
    # =========================
    plant_code = fields.Char(tracking=True)
    plant_name = fields.Char(string="Plant Area", tracking=True)
    business_unit_code = fields.Char(tracking=True)
    business_unit_name = fields.Char(tracking=True)
    work_center = fields.Char(tracking=True)
    functional_location = fields.Char(tracking=True)

    # =========================
    # SNAPSHOT EQUIPMENT (untuk report/search)
    # =========================
    equipment = fields.Char(string="Equipment (Snapshot)", tracking=True)
    spare_part = fields.Char(string="Spare Part (Snapshot)", tracking=True)
    sku = fields.Char(string="SKU (Snapshot)", tracking=True)

    description = fields.Text(tracking=True)

    attachment_ids = fields.Many2many(
        "ir.attachment",
        "tagging_record_ir_attachment_rel",
        "record_id",
        "attachment_id",
        string="Photos",
    )

    status = fields.Selection(
        [
            ("open", "Open"),
            ("validated", "Validated"),
            ("open_wo", "Open - WO"),
            ("postponed", "Postponed"),
            ("closed", "Closed"),
        ],
        default="open",
        tracking=True,
        required=True,
        index=True,
    )

    reject_reason = fields.Text(string="Reject Reason", tracking=True)

    # =========================
    # HARD LOCK WHEN CLOSED
    # =========================
    def write(self, vals):
        for rec in self:
            if rec.status == "closed":
                raise UserError(_("This record is Closed and cannot be edited."))
        return super().write(vals)

    # =========================
    # STATE ACTIONS
    # =========================
    def action_set_open(self):
        for rec in self:
            if rec.status == "closed":
                raise UserError(_("Closed record cannot be reopened."))
        self.write({"status": "open"})

    def action_set_postponed(self):
        for rec in self:
            if rec.status == "closed":
                raise UserError(_("Closed record cannot be changed."))
        self.write({"status": "postponed"})

    def action_validate(self):
        for rec in self:
            if rec.status != "open":
                continue
            rec.write({"status": "validated"})
        return True

    def action_set_wo(self):
        self.ensure_one()
        if self.status != "validated":
            raise UserError(_("Set Work Order hanya bisa setelah Validated."))

        return {
            "type": "ir.actions.act_window",
            "name": _("Input Sparepart WO"),
            "res_model": "tagging.wo.sparepart.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_record_id": self.id,
                "default_line_ids": [(0, 0, {"qty": 1})],
            },
        }


    def action_set_closed(self):
        """
        Close hanya bisa setelah validated/open_wo
        Wajib pilih Equipment (machine_bom_id)
        """
        for rec in self:
            if rec.status == "closed":
                continue

            if rec.status not in ("validated", "open_wo"):
                raise UserError(_("Close hanya bisa setelah Validated / Open - WO."))

            if not rec.machine_bom_id:
                raise UserError(_("Pilih Equipment (Master) dulu sebelum Close."))

            bom = rec.machine_bom_id

            # snapshot untuk report/search
            vals = {
                # snapshot equipment/sparepart/sku
                "equipment": bom.unit_id.name if bom.unit_id else "",
                "spare_part": bom.spare_part_id.name if bom.spare_part_id else "",
                "sku": bom.sku or (bom.spare_part_id.sku if bom.spare_part_id else ""),
            }

            # set status paling akhir (biar gak ketabrak hard lock)
            super(TaggingRecord, rec).write(vals)
            super(TaggingRecord, rec).write({"status": "closed"})

        return True

    def action_open_reject_wizard(self):
        self.ensure_one()
        if self.status != "open":
            raise UserError(_("Only Open record can be rejected."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Reject Tagging"),
            "res_model": "tagging.record.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_record_id": self.id},
        }

    # =========================
    # CREATE SEQUENCE
    # =========================
    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq.next_by_code("tagging.record") or _("New")
        return super().create(vals_list)

    # -------------------------
    # Helpers
    # -------------------------
    def _m2o_name(self, v, default="Others"):
        # read_group many2one: (id, name)
        if isinstance(v, (list, tuple)) and len(v) >= 2:
            return v[1] or default
        return v or default

    # =========================
    # DASHBOARD (FIXED)
    # =========================
    @api.model
    def get_dashboard_stats(self, payload=None):
        payload = payload or {}
        Model = self.sudo()
        domain = []

        # ---- Filters ----
        plant = payload.get("plant_code")
        if plant:
            domain.append(("plant_code", "=", plant))

        bu = payload.get("business_unit_code")
        if bu:
            domain.append(("business_unit_code", "=", bu))

        st = payload.get("status")
        if st:
            domain.append(("status", "=", st))

        dr = payload.get("date_range")
        if dr in ("today", "7d", "30d"):
            now = fields.Datetime.now()
            if dr == "today":
                start = fields.Datetime.to_string(fields.Datetime.start_of(now, "day"))
            elif dr == "7d":
                start = fields.Datetime.to_string(now - timedelta(days=7))
            else:
                start = fields.Datetime.to_string(now - timedelta(days=30))
            domain.append(("create_date", ">=", start))

        # ---- KPI ----
        open_count = Model.search_count(domain + [("status", "=", "open")])
        closed_count = Model.search_count(domain + [("status", "=", "closed")])
        postponed_count = Model.search_count(domain + [("status", "=", "postponed")])
        total_count = Model.search_count(domain)

        # ---- Metrics (gambar 2) ----
        pct_closed = (closed_count / total_count * 100.0) if total_count else 0.0

        # kamu belum punya is_valid, jadi kita definisikan:
        # Not Valid = status open (biar ada angka dan konsisten)
        pct_not_valid = (open_count / total_count * 100.0) if total_count else 0.0

        # ---- Status chart (optional, kompatibel lama) ----
        grouped_status = Model._read_group(domain=domain, groupby=["status"], aggregates=["__count"])
        status_map = {k: 0 for k in ["open", "validated", "open_wo", "postponed", "closed"]}
        for row in grouped_status:
            st_val = row[0]
            cnt = row[1] if len(row) > 1 else 0
            if st_val in status_map:
                status_map[st_val] = cnt

        # ==========================================================
        # BAR: Category System (paling benar: Machine BOM -> System)
        # Fallback: master problem "sistem" kalau machine_bom_id kosong
        # ==========================================================
        by_system = {"labels": [], "values": []}

        labels = []
        values = []
        # 1) group by machine_bom_id.system_id
        # read_group supports grouping by related m2o path
        try:
            grouped_sys = Model.read_group(domain, ["id"], ["machine_bom_id.system_id"], lazy=False)
            for g in grouped_sys:
                sys_val = g.get("machine_bom_id.system_id")
                labels.append(self._m2o_name(sys_val, "Others"))
                values.append(g.get("__count", 0))
        except Exception:
            grouped_sys = []

        # 2) fallback kalau semua masih Others atau kosong: pakai category_problem_id.sistem (Char)
        # Ini bikin chart tetap hidup untuk record belum pilih machine_bom_id
        if (not labels) or (len(labels) == 1 and labels[0] == "Others"):
            labels = []
            values = []
            try:
                grouped_fallback = Model.read_group(domain, ["id"], ["category_problem_id"], lazy=False)
                # ambil sistem dari master category.problem
                # kita hitung manual di python (karena sistem = char di model lain)
                counter = {}
                for g in grouped_fallback:
                    cp = g.get("category_problem_id")
                    cp_id = cp[0] if isinstance(cp, (list, tuple)) and cp else False
                    cnt = g.get("__count", 0)
                    if not cp_id:
                        counter["Others"] = counter.get("Others", 0) + cnt
                        continue
                    rec = self.env["category.problem"].sudo().browse(cp_id)
                    key = rec.sistem or "Others"
                    counter[key] = counter.get(key, 0) + cnt

                labels = list(counter.keys())
                values = [counter[k] for k in labels]
            except Exception:
                pass

        by_system = {"labels": labels, "values": values}

        # ==========================================================
        # BAR: Category Problem (pakai snapshot Char store)
        # ==========================================================
        by_problem = {"labels": [], "values": []}
        if "problem_category" in Model._fields:
            grouped_prob = Model.read_group(domain, ["id"], ["problem_category"], lazy=False)
            p_labels = []
            p_values = []
            for g in grouped_prob:
                p_labels.append(g.get("problem_category") or "Others")
                p_values.append(g.get("__count", 0))
            by_problem = {"labels": p_labels, "values": p_values}

        # ==========================================================
        # TREEMAP: System x Subsystem (dari machine_bom_id)
        # group = system, label = subsystem, value = count
        # fallback: sistem/sub_sistem dari category.problem jika bom kosong
        # ==========================================================
        treemap_nodes = []
        try:
            grouped_tree = Model.read_group(domain, ["id"], ["machine_bom_id.system_id", "machine_bom_id.subsystem_id"], lazy=False)
            for g in grouped_tree:
                sys_val = self._m2o_name(g.get("machine_bom_id.system_id"), "Others")
                sub_val = self._m2o_name(g.get("machine_bom_id.subsystem_id"), "Others")
                treemap_nodes.append({
                    "label": sub_val,
                    "value": g.get("__count", 0),
                    "group": sys_val,
                })
        except Exception:
            grouped_tree = []

        # fallback kalau treemap kosong: pakai category.problem (sistem/sub_sistem)
        if not treemap_nodes:
            try:
                grouped_cp = Model.read_group(domain, ["id"], ["category_problem_id"], lazy=False)
                counter = {}  # key = (sistem, sub_sistem)
                for g in grouped_cp:
                    cp = g.get("category_problem_id")
                    cp_id = cp[0] if isinstance(cp, (list, tuple)) and cp else False
                    cnt = g.get("__count", 0)
                    if not cp_id:
                        key = ("Others", "Others")
                    else:
                        rec = self.env["category.problem"].sudo().browse(cp_id)
                        key = (rec.sistem or "Others", rec.sub_sistem or "Others")
                    counter[key] = counter.get(key, 0) + cnt

                for (sys_name, sub_name), cnt in counter.items():
                    treemap_nodes.append({
                        "label": sub_name,
                        "value": cnt,
                        "group": sys_name,
                    })
            except Exception:
                pass

        # ==========================================================
        # TABLE: % Closed & Not Closed per System (mirip tabel ABC)
        # ==========================================================
        abc_table = []
        if by_system["labels"]:
            for sys_name, total_sys in zip(by_system["labels"], by_system["values"]):
                if not total_sys:
                    continue

                # domain per system:
                # kalau sistem berasal dari BOM -> filter via machine_bom_id.system_id.name (pakai search pada bom)
                # cara paling aman: cari BOM system_id.name == sys_name lalu filter machine_bom_id in [...]
                sys_domain = list(domain)

                # coba BOM filter dulu
                bom_ids = self.env["tagging.machine_bom"].sudo().search([
                    ("system_id.name", "=", sys_name)
                ]).ids

                if bom_ids:
                    sys_domain = sys_domain + [("machine_bom_id", "in", bom_ids)]
                else:
                    # fallback: filter via category_problem_id.sistem
                    # (tidak bisa domain langsung via related char tanpa store)
                    # jadi hitung closed manual:
                    recs = Model.search(sys_domain)
                    closed_in_sys = 0
                    total_in_sys = 0
                    for r in recs:
                        # ambil sistem dari category.problem
                        if r.category_problem_id and (r.category_problem_id.sistem or "") == sys_name:
                            total_in_sys += 1
                            if r.status == "closed":
                                closed_in_sys += 1
                    pct_c = (closed_in_sys / total_in_sys * 100.0) if total_in_sys else 0.0
                    pct_nc = (100.0 - pct_c) if total_in_sys else 0.0
                    abc_table.append({
                        "abc": sys_name,
                        "total": total_in_sys,
                        "pct_closed": round(pct_c, 2),
                        "pct_not_closed": round(pct_nc, 2),
                    })
                    continue

                closed_in_sys = Model.search_count(sys_domain + [("status", "=", "closed")])
                total_in_sys = Model.search_count(sys_domain)
                pct_c = (closed_in_sys / total_in_sys * 100.0) if total_in_sys else 0.0
                pct_nc = (100.0 - pct_c) if total_in_sys else 0.0

                abc_table.append({
                    "abc": sys_name,
                    "total": total_in_sys,
                    "pct_closed": round(pct_c, 2),
                    "pct_not_closed": round(pct_nc, 2),
                })

            # urutkan by total desc biar bagus
            abc_table.sort(key=lambda x: x["total"], reverse=True)

        return {
            # lama
            "kpi": {
                "open": open_count,
                "closed": closed_count,
                "postponed": postponed_count,
                "total": total_count,
            },
            "chart": {
                "labels": ["Open", "Validated", "Open - WO", "Postponed", "Closed"],
                "values": [
                    status_map["open"],
                    status_map["validated"],
                    status_map["open_wo"],
                    status_map["postponed"],
                    status_map["closed"],
                ],
            },

            # baru
            "metrics": {
                "total": total_count,
                "pct_closed": round(pct_closed, 2),
                "pct_not_valid": round(pct_not_valid, 2),
            },
            "by_system": by_system,
            "by_problem": by_problem,
            "treemap_abc_system": treemap_nodes,
            "abc_table": abc_table,
        }
        
     
    @api.model
    def get_dashboard_filter_options(self):
        Model = self.sudo()

        # plants dari record (snapshot)
        plants = Model.search_read([("plant_code", "!=", False)], ["plant_code"], order="plant_code asc")
        plant_codes = sorted({p["plant_code"] for p in plants if p.get("plant_code")})

        # business unit dari record (snapshot)
        bus = Model.search_read([("business_unit_code", "!=", False)], ["business_unit_code"], order="business_unit_code asc")
        business_units = sorted({b["business_unit_code"] for b in bus if b.get("business_unit_code")})

        return {
            "date_ranges": [
                {"key": "today", "label": "Today"},
                {"key": "7d", "label": "Last 7 days"},
                {"key": "30d", "label": "Last 30 days"},
                {"key": "all", "label": "All time"},
            ],
            "plants": plant_codes,
            "business_units": business_units,
            "statuses": [
                {"key": "", "label": "All Status"},
                {"key": "open", "label": "Open"},
                {"key": "validated", "label": "Validated"},
                {"key": "open_wo", "label": "Open - WO"},
                {"key": "postponed", "label": "Postponed"},
                {"key": "closed", "label": "Closed"},
            ],
        }
        