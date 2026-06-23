from odoo import api, fields, models, _
from datetime import timedelta
from odoo.exceptions import UserError
from collections import defaultdict
from odoo.tools import html_escape as escape
import logging
_logger = logging.getLogger(__name__)



class TaggingRecord(models.Model):
    _name = "tagging.record"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Tagging Record"
    _order = "create_date desc"

    name = fields.Char(string="Ticket", readonly=True, copy=False, default="New")
    active = fields.Boolean(default=True)

    user_id = fields.Many2one(
        "res.users",
        string="Created By",
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
    )

    wo_sparepart_ids = fields.One2many(
        "tagging.wo.sparepart",
        "record_id",
        string="WO Spareparts",
    )
   
    
  
    abc_indic = fields.Char(
        string="ABC Indic",
        related="barcode_id.abc_indic",
        store=True,
        readonly=True,
    )
    abc_indicator = fields.Char(string="Indicator", related="barcode_id.abc_indic", store=True, readonly=True)


    tagger_name = fields.Char(required=True, tracking=True)
    tagger_email = fields.Char(string="Tagger Email")

    # =========================
    # MASTER LINKS (WEBSITE FORM)
    # =========================
    barcode_id = fields.Many2one(
        "barcode.tagging",
        string="Barcode",
        ondelete="restrict",
        tracking=True,
    )   
    
    department_ids = fields.Many2many(
        comodel_name="tagging.department",
        string="Department (PIC)",
        related="pic_id.department_ids",
        readonly=True,
    )


    pic_id = fields.Many2one(
        "tagging.pic",
        string="PIC",
        ondelete="restrict",
        tracking=True,
    )

    category_problem_id = fields.Many2one(
        "category.problem",
        string="Category Problem",
        ondelete="restrict",
        tracking=True,
    )

    # snapshot (store) biar gampang search/report
    pic_name = fields.Char(string="PIC Email", related="pic_id.email", store=True, tracking=True)
    pic_department_names = fields.Char(
    string="PIC Department",
    )
    problem_category = fields.Char(string="Problem Category", related="category_problem_id.cat_masalah", store=True, tracking=True)
    problem_id = fields.Many2one(string="Problem", related="category_problem_id.problem_id", store=True, tracking=True)

    # =========================
    # EQUIPMENT MASTER (legacy - existing)
    # =========================
    machine_bom_id = fields.Many2one(
        "tagging.machine_bom",
        string="Equipment (Master)",
        ondelete="restrict",
        tracking=True,
    )
    
    allowed_spare_part_ids = fields.Many2many(
        "tagging.spare_part",
        compute="_compute_allowed_spare_part_ids",
        store=False,
        readonly=True,
    )


    # =========================
    # SNAPSHOT LOKASI (dari barcode)
    # =========================
    plant_code = fields.Char(tracking=True)
    plant_name = fields.Char(string="Plant Area", tracking=True)
    work_center = fields.Char(string="Work Center")
    functional_location = fields.Char(string="FuncLoc",tracking=True)

    # =========================
    # SNAPSHOT EQUIPMENT (untuk report/search)
    # =========================
    equipment = fields.Char(string="Equipment (Snapshot)", tracking=True)
#     available_equipment_ids = fields.Many2many(
#     "maintenance.equipment",
#     compute="_compute_available_equipments",
#     store=False,
# )
    spare_part = fields.Char(string="Spare Part (Snapshot)", tracking=True)
    sku = fields.Char(string="SKU (Snapshot)", tracking=True)

    # =========================
    # DATE TRACKING
    # =========================
    start_date = fields.Datetime(string="Start Date", tracking=True, default=fields.Datetime.now())
    end_date = fields.Datetime(string="End Date", tracking=True)

    # =========================
    # NEW FLOW: Parent/Sub Equipment + Sparepart (Maintenance + Product SKU)
    # =========================
    parent_equipment_id = fields.Many2one(
        "maintenance.equipment",
        string="Superord Equipment",
        tracking=True,
    )

    equipment_id = fields.Many2one(
        "maintenance.equipment",
        string="Equipment",
        tracking=True,
    )
    parent_equipment_name = fields.Char(
    related="parent_equipment_id.name",
    store=False,
    readonly=True,
    )

    system = fields.Char(
        string="System String",
        related="barcode_id.superord_functional_loc",
        store=True,
        readonly=True,
    )
    system_name = fields.Char(string="System Name", tracking=True)
    sub_system_name = fields.Char(string="Sub System Name", tracking=True)
    system_id = fields.Many2one("tagging.system", string="System", ondelete="restrict")
    sub_system_id = fields.Many2one("tagging.subsystem", string="Sub System", ondelete="restrict")
    sub_system_code = fields.Char(
        related='sub_system_id.code',
        string='Sub System Code',
        store=True,
        readonly=True
    )
    maintenance_team_id = fields.Many2one(
        "maintenance.team",
        string="Maintenance Team",
        tracking=True,
    )

    available_sparepart_ids = fields.Many2many(
        "product.product",
        compute="_compute_available_spareparts",
        store=False,
    )
    
    sparepart_product_id = fields.Many2one(
    "product.product",
    string="Sparepart",
    tracking=True,
)
   
    
    functional_location_code = fields.Char(
    string="Functional Location Code",
    compute="_compute_functional_location_code",
    store=True,
    readonly=True,
)


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
            ("closed", "Closed"),
            ("rejected", "Rejected"),
            ("cancelled", "Cancelled"),
        ],
        default="open",
        tracking=True,
        required=True,
    )

    reject_reason = fields.Text(string="Reject Reason", tracking=True)

    # --- Close Evidence ---
    close_photo = fields.Image(string="Close Photo", max_width=1024, max_height=1024)

    close_start_date = fields.Datetime(string="Close Start Date")
    close_end_date = fields.Datetime(string="Close End Date")

    close_description = fields.Text(string="Problem Solution")

    close_photo_filename = fields.Char(string="Photo Filename")

    close_description = fields.Text(
        string="Deskripsi Penutupan",
        tracking=True,
    )
    
    # tambahan gaez
    department_id = fields.Many2one(comodel_name='tagging.department', string="Department")
    is_locked = fields.Boolean(string="Is Locked", default=False)
    company_id = fields.Many2one(comodel_name='res.company', string="Company", default=lambda self: self.env.company)
    close_reason = fields.Text(string="Reason Details")

    # =========================
    # HARD LOCK WHEN CLOSED
    # =========================
    def write(self, vals):
        for rec in self:
            # allow archive / unarchive even if closed
            only_active_toggle = set(vals.keys()) == {"active"}

            if rec.status == "closed" and not only_active_toggle:
                raise UserError(_("This record is Closed and cannot be edited."))

        return super().write(vals)

    @api.depends("equipment_id")
    def _compute_available_spareparts(self):
        for rec in self:
            if rec.equipment_id:
                rec.available_sparepart_ids = rec.equipment_id.product_line_ids.mapped("product_id")
            else:
                rec.available_sparepart_ids = self.env["product.product"]
    
    @api.depends("parent_equipment_id", "equipment_id")
    def _compute_functional_location_code(self):
        for rec in self:
            parent_code = getattr(rec.parent_equipment_id, "functional_location_code", False) or ""
            equip_code = getattr(rec.equipment_id, "functional_location_code", False) or ""
            rec.functional_location_code = parent_code or equip_code or ""
            
    # @api.onchange("equipment_id")
    # def _onchange_equipment_id_reset_sparepart(self):
    #     self.sparepart_product_id = False

    #     domain = [("id", "=", 0)]  # default kosong
    #     if self.equipment_id:
    #         product_ids = self.equipment_id.product_line_ids.mapped("product_id").ids
    #         domain = [("id", "in", product_ids)] if product_ids else [("id", "=", 0)]

    #     return {"domain": {"sparepart_product_id": domain}}

    @api.onchange("barcode_id", "maintenance_team_id")
    def _onchange_barcode_id_parent_equipment_domain(self):
        self.parent_equipment_id = False
        self.equipment_id = False
        self.sparepart_product_id = False

    @api.depends("equipment_id.equipment_no")
    def _compute_equipment_no(self):
        for rec in self:
            rec.equipment_no = rec.equipment_id.equipment_no or ""

    @api.depends("parent_equipment_id.equipment_no")
    def _compute_parent_equipment_no(self):
        for rec in self:
            rec.parent_equipment_no = rec.parent_equipment_id.equipment_no or ""
    
    @api.onchange("barcode_id", "functional_location", "maintenance_team_id")
    def _onchange_fl_or_team_parent_domain(self):
            self.parent_equipment_id = False
            self.equipment_id = False
            self.sparepart_product_id = False

            domain = [("id", "=", 0)]

            # kalau kamu punya relasi fl sebagai Many2one, ini paling ideal:
            fl = False
            if self.barcode_id and getattr(self.barcode_id, "functional_loc_tagging_id", False):
                fl = self.barcode_id.functional_loc_tagging_id

            if fl:
                domain = [
                    ("parent_id", "=", False),  # superior kosong (sesuaikan kalau field beda)
                    ("functional_loc_tagging_id", "=", fl.id),
                ]
                if self.maintenance_team_id and "maintenance_team_id" in self.env["maintenance.equipment"]._fields:
                    domain.append(("maintenance_team_id", "=", self.maintenance_team_id.id))

            return {"domain": {"parent_equipment_id": domain}}

    def action_qty_minus(self):
        for line in self:
            line.qty = max(0.0, (line.qty or 0.0) - 1.0)

    def action_qty_plus(self):
        for line in self:
            line.qty = (line.qty or 0.0) + 1.0
    
    @api.onchange("barcode_id")
    def _onchange_barcode_snapshot_names(self):
        for rec in self:
            if not rec.barcode_id:
                rec.system = False
                rec.system_name = False
                rec.sub_system_name = False
                return

            rec.system = rec.barcode_id.superord_functional_loc
            rec.system_name = rec._resolve_system_name(rec.system)

            # sub system name langsung dari barcode yg discan
            rec.sub_system_name = rec.barcode_id.functional_location_name or rec.barcode_id.functional_location


    @api.onchange("functional_location", "maintenance_team_id")
    def _onchange_functional_location_domain(self):
            self.parent_equipment_id = False
            self.equipment_id = False
            self.sparepart_product_id = False

            dom_parent = [("id", "=", 0)]
            if self.functional_location:
                dom_parent = [
                    ("functional_loc", "=", self.functional_location), 
                    ("parent_id", "=", False),                        
                ]

                # optional filter team kalau memang ada fieldnya di equipment
                if self.maintenance_team_id and "maintenance_team_id" in self.env["maintenance.equipment"]._fields:
                    dom_parent.append(("maintenance_team_id", "=", self.maintenance_team_id.id))

            return {"domain": {"parent_equipment_id": dom_parent}}

    
    
    @api.depends("equipment_id")
    def _compute_allowed_spare_part_ids(self):
        # Product = self.env["product.product"].sudo()
        Product = self.env["tagging.spare_part"].sudo()
        LineTmp = self.env["tagging.wo.sparepart.wizard.line"].sudo()
        print("0000000000000000000000000000000")
        for rec in self:
            eq = rec.equipment_id
            print(f"99999999999999999999 {eq}")
            if not eq:
                rec.allowed_spare_part_ids = Product.browse([])
                continue

            tmp = LineTmp.new({})
            plines = tmp._get_equipment_product_lines(eq)
            print(f"88888888888888888888888888 {plines}")
            if not plines:
                rec.allowed_spare_part_ids = Product.browse([])
                continue

            product_ids = tmp._extract_product_ids_from_plines(plines)
            rec.allowed_spare_part_ids = Product.browse(product_ids or [])
    # =========================
       
    # STATE ACTIONS
    # =========================
    def action_set_open(self):
            for rec in self:
                if rec.status == "closed":
                    raise UserError(_("Closed record cannot be reopened."))
            self.write({"status": "open"})
    
    def action_cancelled(self):
       for rec in self:
            if rec.status == 'open_wo':
                rec.status = 'cancelled'
            else:
                raise UserError("Can only cancel in Open WO Status")

    def action_validate(self):
        now = fields.Datetime.now()
        for rec in self:
            if rec.status != "open":
                continue
            vals = {"status": "validated"}
            # start_date mulai dihitung saat validated (kalau belum ada)
            # if not rec.start_date:
            #     vals["start_date"] = now
            rec.write(vals)
        return True

    def action_set_wo(self):
        self.ensure_one()
        if self.status != "validated":
            raise UserError(_("Set Work Order hanya bisa setelah Validated."))

        # if not self.start_date:
        #     self.write({"start_date": fields.Datetime.now()})

        ctx = {
            "default_record_id": self.id,
            "default_equipment_id": self.equipment_id.id if self.equipment_id else False, 
        }

        if self.wo_sparepart_ids:
            ctx["default_line_ids"] = [(0, 0, {
                "spare_part_id": line.spare_part_id.id,
                "sku": line.spare_part_id.sku or '',
                "qty": line.qty or 1.0,
                "remarks": line.remarks or "",
            }) for line in self.wo_sparepart_ids]

        return {
            "type": "ir.actions.act_window",
            "name": _("Input Sparepart WO"),
            "res_model": "tagging.wo.sparepart.wizard",
            "view_mode": "form",
            "target": "new",
            "context": ctx,
        }
    
    def _resolve_system_name(self, system_code):
        if not system_code:
            return "Others"
        # cari barcode.tagging yang functional_location == system_code
        b = self.env["barcode.tagging"].sudo().search(
            [("functional_location", "=", system_code)],
            limit=1
        )
        return (b.functional_location_name or b.functional_location or system_code or "Others")

    def action_set_closed(self):
        for rec in self:
            if rec.status == "closed":
                continue
            if rec.status not in ("validated", "open_wo"):
                raise UserError(_("Close hanya bisa setelah Validated / Open - WO."))
            if not rec.close_start_date:
                raise UserError('Close Start Date harus diisi!')
            if not rec.close_end_date:
                raise UserError('Close End Date harus diisi!')
            if not rec.close_description:
                raise UserError(_("Deskripsi Close wajib diisi sebelum Close."))
            if not rec.close_photo:
                raise UserError(_("Photo Close wajib diupload sebelum Close."))

            vals = {
                "status": "closed",
                "end_date": fields.Datetime.now(),
            }

            # ====== NEW FLOW (maintenance.equipment) ======
            if rec.equipment_id:
                vals.update({
                    "equipment": rec.equipment_id.display_name or rec.equipment_id.name or "",
                    "spare_part": rec.sparepart_product_id.display_name if rec.sparepart_product_id else "",
                    # sesuaikan: banyak DB pakai default_code untuk SKU
                    "sku": (rec.sparepart_product_id.default_code if rec.sparepart_product_id else "") or "",
                })

            # ====== LEGACY FLOW (tagging.machine_bom) ======
            elif rec.machine_bom_id:
                bom = rec.machine_bom_id
                vals.update({
                    "equipment": bom.unit_id.name if bom.unit_id else "",
                    "spare_part": bom.spare_part_id.name if bom.spare_part_id else "",
                    "sku": bom.sku or (bom.spare_part_id.sku if bom.spare_part_id else ""),
                })

            else:
                # kalau mau: ganti teks error jadi lebih akurat
                raise UserError(_("Equipment wajib dipilih sebelum Close."))

            # if not rec.start_date:
            #     vals["start_date"] = rec.end_date
            
            if rec.status == 'validated':
                rec.wo_sparepart_ids.sudo().unlink()
                rec.message_post(body=f"Sparepart dihapus karena menggunakan proses CILT")

            super(TaggingRecord, rec).write(vals)

            try:
                rec.sudo()._send_email_close_to_tagger()
            except Exception as e:
                _logger.exception("Gagal kirim email close untuk %s", rec.name)

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

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq.next_by_code("tagging.record") or _("New")

        records = super().create(vals_list)

        for rec in records:
            try:
                rec._send_email_to_department()
            except Exception as e:
                _logger.exception("Gagal kirim email tagging untuk %s", rec.name)
                # optional: catat ke chatter kalau model punya mail.thread
                if hasattr(rec, "message_post"):
                    rec.message_post(body=f"⚠️ Gagal kirim email otomatis: {e}")

        return records

    # @api.depends("parent_equipment_id")
    # def _compute_available_equipments(self):
    #     for rec in self:
    #         rec.available_equipment_ids = rec.parent_equipment_id.child_equipment_ids if rec.parent_equipment_id else self.env["maintenance.equipment"].browse([])

    # @api.onchange("parent_equipment_id")
    # def _onchange_parent_equipment_id(self):
    #     self.equipment_id = False
    #     self.sparepart_product_id = False
    #     child_ids = self.parent_equipment_id.child_equipment_ids.ids if self.parent_equipment_id else []
    #     self.wo_sparepart_ids = [(5, 0, 0)]
    #     return {
    #         "domain": {
    #             "equipment_id": [("id", "in", child_ids)] if child_ids else [("id", "=", 0)]
    #         }
    #     }

    def _m2o_name(self, v, default="Others"):
        if isinstance(v, (list, tuple)) and len(v) >= 2:
            return v[1] or default
        return v or default
 
    @api.model
    def get_dashboard_stats(self, payload=None):
        payload = payload or {}
        Model = self.sudo()
        # domain = [('company_id', '=', self.env.company.id)]
        domain = [('company_id', 'in', self.env.companies.ids)]
        
        plant = payload.get("plant_code")
        if plant:
            domain.append(("plant_code", "=", plant))

        st = payload.get("status")
        if st:
            domain.append(("status", "=", st))

        dr = (payload.get("date_range") or "today").strip()
        date_from = (payload.get("date_from") or "").strip()
        date_to   = (payload.get("date_to") or "").strip()

        now = fields.Datetime.now()

        def dt_str(dt):
            return fields.Datetime.to_string(dt)

        def end_of_day(dt):
            return fields.Datetime.end_of(dt, "day")

        def start_of_day(dt):
            return fields.Datetime.start_of(dt, "day")

        if dr == "today":
            start = start_of_day(now)
            end = end_of_day(now)
            domain += [("create_date", ">=", dt_str(start)), ("create_date", "<=", dt_str(end))]
        elif dr == "yesterday":
            d = now - timedelta(days=1)
            start = start_of_day(d)
            end = end_of_day(d)
            domain += [("create_date", ">=", dt_str(start)), ("create_date", "<=", dt_str(end))]
        elif dr in ("last_7", "7d"):
            start = start_of_day(now - timedelta(days=6))
            end = end_of_day(now)
            domain += [("create_date", ">=", dt_str(start)), ("create_date", "<=", dt_str(end))]
        elif dr in ("last_30", "30d"):
            start = start_of_day(now - timedelta(days=29))
            end = end_of_day(now)
            domain += [("create_date", ">=", dt_str(start)), ("create_date", "<=", dt_str(end))]
        elif dr == "this_month":
            start = fields.Datetime.start_of(now, "month")
            end = fields.Datetime.end_of(now, "month")
            domain += [("create_date", ">=", dt_str(start)), ("create_date", "<=", dt_str(end))]
        else:
            if date_from:
                domain.append(("create_date", ">=", f"{date_from} 00:00:00"))
            if date_to:
                domain.append(("create_date", "<=", f"{date_to} 23:59:59"))

        def norm(v):
            s = (v or "").strip()
            return s if s else "Others"

        open_count = Model.search_count(domain + [("status", "=", "rejected")])
        closed_count = Model.search_count(domain + [("status", "=", "closed")])
        total_count = Model.search_count(domain)

        pct_closed = (closed_count / total_count * 100.0) if total_count else 0.0
        pct_not_valid = (open_count / total_count * 100.0) if total_count else 0.0

        # FIX 2: Implementasi _read_group menggantikan read_group
        status_map = {k: 0 for k in ["open", "validated", "open_wo", "closed"]}
        try:
            for st_val, count in Model._read_group(domain, ["status"], ["__count"]):
                if st_val in status_map:
                    status_map[st_val] = count
        except Exception as e:
            _logger.error("TAGGING DASHBOARD Error generating status_map: %s", e)

        by_abc = {"labels": [], "values": []}
        try:
            counter = defaultdict(int)
            for abc_val, count in Model._read_group(domain, ["abc_indic"], ["__count"]):
                key = norm(abc_val)
                counter[key] += count

            pairs = sorted(counter.items(), key=lambda x: x[1], reverse=True)
            by_abc = {"labels": [p[0] for p in pairs], "values": [p[1] for p in pairs]}
        except Exception as e:
            _logger.error("TAGGING DASHBOARD Error generating by_abc: %s", e)

        by_system = {"labels": [], "values": []}
        try:
            counter = defaultdict(int)
            # Pada _read_group, field M2O (system_id) mengembalikan objek record, bukan tuple
            for sys_rec, count in Model._read_group(domain, ["system_id"], ["__count"]):
                key = sys_rec.name if sys_rec else "Others"
                counter[key] += count

            pairs = sorted(counter.items(), key=lambda x: x[1], reverse=True)
            by_system = {"labels": [p[0] for p in pairs], "values": [p[1] for p in pairs]}
        except Exception as e:
            _logger.error("TAGGING DASHBOARD Error generating by_system: %s", e)

        by_problem = {"labels": [], "values": []}
        if "category_problem_id" in Model._fields:
            try:
                p_counter = defaultdict(int)
                for prob_rec, count in Model._read_group(domain, ["category_problem_id"], ["__count"]):
                    key = prob_rec.cat_masalah if prob_rec else "Others"
                    p_counter[key] += count

                p_pairs = sorted(p_counter.items(), key=lambda x: x[1], reverse=True)
                by_problem = {
                    "labels": [p[0] for p in p_pairs],
                    "values": [p[1] for p in p_pairs],
                }
            except Exception as e:
                _logger.error("TAGGING DASHBOARD Error generating by_problem stats: %s", e)

        treemap_nodes = []
        try:
            t_counter = defaultdict(int)
            # Grouping dengan 2 parameter
            for abc_val, sys_rec, count in Model._read_group(domain, ["abc_indic", "system_id"], ["__count"]):
                abc_key = norm(abc_val)
                sys_name = sys_rec.name if sys_rec else "Others"
                t_counter[(abc_key, sys_name)] += count

            treemap_nodes = [
                {
                    "group": abc_key,     # level 1
                    "system": sys_name,   # level 2 (leaf)
                    "value": cnt,
                }
                for (abc_key, sys_name), cnt in t_counter.items()
            ]
            treemap_nodes.sort(key=lambda x: (x["group"], -x["value"], x["system"]))
        except Exception as e:
            _logger.error("TAGGING DASHBOARD Error generating treemap_: %s", e)

        abc_table = []
        try:
            agg = defaultdict(lambda: {"total": 0, "closed": 0})
            for abc_val, st_val, count in Model._read_group(domain, ["abc_indic", "status"], ["__count"]):
                abc_key = norm(abc_val)
                agg[abc_key]["total"] += count
                if st_val == "closed":
                    agg[abc_key]["closed"] += count

            for abc_val, d in agg.items():
                total_in_abc = d["total"]
                closed_in_abc = d["closed"]
                pct_c = (closed_in_abc / total_in_abc * 100.0) if total_in_abc else 0.0
                pct_nc = (100.0 - pct_c) if total_in_abc else 0.0
                abc_table.append({
                    "abc": abc_val,
                    "total": total_in_abc,
                    "pct_closed": round(pct_c, 2),
                    "pct_not_closed": round(pct_nc, 2),
                })

            abc_table.sort(key=lambda x: x["total"], reverse=True)
        except Exception as e:
            _logger.error("TAGGING DASHBOARD Error generating abc_table: %s", e)

        abc_system_grouping = {}
        try:
            tmp = defaultdict(lambda: defaultdict(int))
            for abc_val, sys_rec, count in Model._read_group(domain, ["abc_indic", "system_id"], ["__count"]):
                abc_key = norm(abc_val)
                sys_name = sys_rec.name if sys_rec else "Others"
                tmp[abc_key][sys_name] += count

            for abc_key, sys_map in tmp.items():
                rows = [{"system": s, "count": c} for s, c in sys_map.items()]
                rows.sort(key=lambda x: (-x["count"], x["system"]))
                abc_system_grouping[abc_key] = rows

            def key_order(k):
                if k in ("A", "B", "C"):
                    return (0, k)
                if k == "Others":
                    return (2, k)
                return (1, k)

            abc_system_grouping = dict(sorted(abc_system_grouping.items(), key=lambda kv: key_order(kv[0])))

        except Exception as e:
            _logger.error("TAGGING DASHBOARD Error generating abc_system_group: %s", e)
        
        abc_system_grouping_items = [
            {"abc": k, "rows": v}
            for k, v in (abc_system_grouping or {}).items()
        ]
        
        return {
            "kpi": {"open": open_count, "closed": closed_count, "total": total_count},
            "chart": {
                "labels": ["Open", "Validated", "Open - WO", "Closed"],
                "values": [
                    status_map["open"],
                    status_map["validated"],
                    status_map["open_wo"],
                    status_map["closed"],
                ],
            },
            "metrics": {
                "total": total_count,
                "pct_closed": round(pct_closed, 2),
                "pct_not_valid": round(pct_not_valid, 2),
            },
            "by_abc": by_abc,
            "by_system": by_system,
            "by_problem": by_problem,
            "treemap_abc_system": treemap_nodes,
            "abc_table": abc_table,
            "abc_system_grouping": abc_system_grouping,
            "abc_system_grouping_items": abc_system_grouping_items, 
        }

    @api.model
    def get_dashboard_filter_options(self):
        Model = self.sudo()

        # Plants
        plant_codes = []
        if "plant_code" in Model._fields:
            plants = Model.search_read(
                [("plant_code", "!=", False)],
                ["plant_code"],
                order="plant_code asc"
            )
            plant_codes = sorted({p["plant_code"] for p in plants if p.get("plant_code")})

        # Statuses (fixed options)
        statuses = [
            {"key": "", "label": "All Status"},
            {"key": "open", "label": "Open"},
            {"key": "validated", "label": "Validated"},
            {"key": "open_wo", "label": "Open - WO"},
            {"key": "closed", "label": "Closed"},
        ]

        # Date ranges (fixed options)
        date_ranges = [
            {"key": "today", "label": "Today"},
            {"key": "7d", "label": "Last 7 days"},
            {"key": "30d", "label": "Last 30 days"},
        ]

        return {
            "date_ranges": date_ranges,
            "plants": plant_codes,
            "statuses": statuses,
            "business_units": [],
        }
    
    
    def _tagging_open_url(self):
        self.ensure_one()
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        return f"{base_url}/web#id={self.id}&model=tagging.record&view_type=form"

    def _format_dt_id(self, dt):
        # format: DD MONTH YYYY pukul HH:MM (timezone user)
        dt = dt or fields.Datetime.now()
        dt_local = fields.Datetime.context_timestamp(self, dt)
        return dt_local.strftime("%d %B %Y pukul %H:%M")

    @api.model
    def cron_remind_open_tagging(self):
        self = self.sudo()
        Tagging = self.env['tagging.record']
        open_taggings = Tagging.search([('status', 'not in', ('closed', 'rejected', 'cancelled'))])
        if not open_taggings:
            return True

        tagging_by_dept = defaultdict(list)
        for ot in open_taggings:
            if ot.department_id:
                tagging_by_dept[ot.department_id].append(ot)

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        mails = []

        for dept, records in tagging_by_dept.items():
            emails = []
            ccs = []
            for pic in dept.pic_ids:
                if pic.email:
                    emails.append(pic.email)
                if pic.cc:
                    ccs.append(pic.cc)

            emails = list(set(emails))
            ccs = list(set(ccs))

            if not emails:
                continue

            rows = ""
            for i, ot in enumerate(records, start=1):
                open_url = f"{base_url}/web#id={ot.id}&model=tagging.record&view_type=form"
                rows += f"""
                    <tr>
                        <td>{i}</td>
                        <td><a href="{open_url}">{escape(ot.name or '')}</a></td>
                        <td>{escape(ot.system_name or '')}</td>
                        <td>{escape(ot.sub_system_id.name or '')}</td>
                        <td>{escape(ot.status or '')}</td>
                        <td>{escape(ot.description or '')}</td>
                        <td>{escape(ot.problem_id.name or '')}</td>
                        <td>{escape(ot.tagger_name or (ot.user_id.name if ot.user_id else ''))}</td>
                    </tr>
                """
            subject = f"[REMINDER] Open Tagging ({len(records)} items)"
            body_html = f"""
                <p>Dear Team,</p>
                <p>Berikut adalah daftar tagging yang masih belum selesai:</p>
                <table border="1" cellspacing="0" cellpadding="5" style="border-collapse: collapse; font-size: 12px;">
                    <thead style="background-color:#f2f2f2;">
                        <tr>
                            <th>No</th>
                            <th>Name</th>
                            <th>System</th>
                            <th>Sub System</th>
                            <th>Status</th>
                            <th>Description</th>
                            <th>Problem Category</th>
                            <th>Tagger</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows}
                    </tbody>
                </table>
                <p>Mohon segera ditindaklanjuti.</p>
                <p>Terima kasih.</p>
            """
            
            mail_values = {
                "subject": subject,
                "body_html": body_html,
                "email_to": ",".join(emails),
                "email_from": "noreply-ops@cpp.co.id",
                "reply_to": "noreply-ops@cpp.co.id",
                "message_type": "email", 
            }
            if ccs:
                mail_values["email_cc"] = ",".join(ccs)
                
            mails.append(mail_values)

        if mails:
            self.env['mail.mail'].sudo().create(mails)

    def _send_reminder_listing_to_department(self):
        """Kirim email reminder listing untuk recordset self (multi)."""
        if not self:
            return False

        first = self[0]
        to_emails = []
        to_ccs = []

        if first.department_id:
            for pic in first.department_id.pic_ids:
                if getattr(pic, "email", False):
                    to_emails.append(pic.email.strip())
                if getattr(pic, "cc", False):
                    to_ccs.append(pic.cc.strip())

        to_emails = list(dict.fromkeys([e for e in to_emails if e]))
        to_ccs = list(dict.fromkeys([c for c in to_ccs if c]))

        if not to_emails:
            _logger.info(
                "No recipient email for reminder (Department=%s)",
                first.department_id.display_name if first.department_id else "-"
            )
            return False

        dept_label = first.department_id.name if first.department_id else "PIC"

        subject = f"Reminder Tagging Belum Closed [{first._format_dt_id(fields.Datetime.now())}]"

        rows_html = ""
        idx = 0
        for rec in self.sorted(key=lambda r: r.create_date or fields.Datetime.now()):
            idx += 1

            system_display = (
                (rec.system_id.display_name if rec.system_id else "")
                or (rec.system_name or "")
                or (rec.barcode_id.system_id.display_name if rec.barcode_id and getattr(rec.barcode_id, "system_id", False) else "")
                or (rec.system or "")
                or "-"
            )
            subsystem_display = (
                (rec.sub_system_id.display_name if rec.sub_system_id else "")
                or (rec.sub_system_name or "")
                or (rec.barcode_id.subsystem_id.display_name if rec.barcode_id and getattr(rec.barcode_id, "subsystem_id", False) else "")
                or (rec.functional_location or "")
                or "-"
            )

            tanggal_str = rec._format_dt_id(rec.create_date) if rec.create_date else "-"
            cat_name = rec.category_problem_id.display_name if rec.category_problem_id else (rec.problem_id.name or "-")
            desc = rec.description or ""

            # status label
            status_label = dict(rec._fields["status"].selection).get(rec.status, rec.status)

            rows_html += f"""
            <tr>
            <td>{idx}</td>
            <td>{escape(rec.name or "")}</td>
            <td>{escape(tanggal_str)}</td>
            <td>{escape(system_display)}</td>
            <td>{escape(subsystem_display)}</td>
            <td>{escape(cat_name)}</td>
            <td>{escape(desc)}</td>
            <td>{escape(status_label)}</td>
            </tr>
            """

        body_html = f"""
        <p>Dear tim {escape(dept_label)},</p>
        <p>Mohon untuk tagging yang masih belum di close agar segera di tindak lanjuti / di selesaikan. Agar statusnya tidak menggantung.</p>

        <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;">
        <thead>
            <tr>
            <th>No</th>
            <th>No. Tagging</th>
            <th>Tanggal</th>
            <th>System</th>
            <th>Sub System</th>
            <th>Cat Problem</th>
            <th>Deskripsi</th>
            <th>Status</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
        </table>

        <p>Terima kasih.</p>
        <p><i>Note: menampilkan semua tagging selain yang Closed.</i></p>
        """

        mail_vals = {
            "subject": subject,
            "body_html": body_html,
            "email_to": ",".join(to_emails),
            "email_from": "noreply-ops@cpp.co.id",
            "reply_to": "noreply-ops@cpp.co.id",
        }

        if to_ccs:
            mail_vals["email_cc"] = ",".join(to_ccs)

        self.env["mail.mail"].sudo().create(mail_vals)
        return True

    def _send_email_to_department(self):
        self.ensure_one()
        to_emails = []
        to_ccs = []

        if self.department_id:
            for pic in self.department_id.pic_ids:
                if getattr(pic, "email", False):
                    to_emails.append(pic.email.strip())
                if getattr(pic, "cc", False):
                    to_ccs.append(pic.cc.strip())

        to_emails = list(dict.fromkeys([e for e in to_emails if e]))
        to_ccs = list(dict.fromkeys([c for c in to_ccs if c]))
        if not to_emails:
            _logger.info(
                "No recipient email for %s (Department=%s)",
                self.name, 
                self.department_id.display_name if self.department_id else "-"
            )
            return False

        subject = f"Laporan abnormal [{self._format_dt_id(self.create_date)}]"

        dept_label = self.department_id.name if self.department_id else "PIC"
        tagger_name = self.tagger_name or (self.user_id.name or "")
        tagger_email = self.user_id.login or ""
        tanggal_str = self._format_dt_id(self.create_date)
        category_name = self.category_problem_id.display_name if self.category_problem_id else ""
        desc = self.description or ""
        open_url = self._tagging_open_url()

        system_display = (
            (self.system_id.display_name if self.system_id else "")
            or (self.system_name or "")
            or (self.barcode_id.system_id.display_name if self.barcode_id and getattr(self.barcode_id, "system_id", False) else "")
            or (self.system or "")
            or "-"
        )

        subsystem_display = (
            (self.sub_system_id.display_name if self.sub_system_id else "")
            or (self.sub_system_name or "")
            or (self.barcode_id.subsystem_id.display_name if self.barcode_id and getattr(self.barcode_id, "subsystem_id", False) else "")
            or (self.functional_location or "")
            or "-"
        )

        body_html = f"""
        <p>Dear tim {escape(dept_label)},</p>
        <p>Telah dibuat tagging baru dengan detail sebagai berikut:</p>
        <ul>
          <li><b>ID Tag:</b> {escape(self.name or "")}</li>
          <li><b>Tagger:</b> {escape(tagger_name)}{' &amp;&amp; ' + escape(tagger_email) if tagger_email else ''}</li>
          <li><b>Tanggal &amp; Waktu Temuan:</b> {escape(tanggal_str)}</li>
          <li><b>Status:</b> Open</li>
          <li><b>System:</b> {escape(system_display)}</li>
          <li><b>Sub System:</b> {escape(subsystem_display)}</li>
          <li><b>Kategori Masalah:</b> {escape(category_name)}</li>
          <li><b>Deskripsi temuan:</b> {escape(desc)}</li>
        </ul>
        <p><a href="{open_url}">Buka Tagging</a></p>
        """

        mail_vals = {
            "subject": subject,
            "body_html": body_html,
            "email_to": ",".join(to_emails),
            "email_from": "noreply-ops@cpp.co.id",
            "reply_to": tagger_email or "noreply-ops@cpp.co.id",
        }

        if to_ccs:
            mail_vals["email_cc"] = ",".join(to_ccs)

        self.env["mail.mail"].sudo().create(mail_vals)
        return True
    
    def _send_email_close_to_tagger(self):
        self.ensure_one()

        to_email = (self.tagger_email or "").strip()

        if not to_email and self.user_id:
            to_email = ((self.user_id.partner_id.email or "").strip()
                        or (self.user_id.login or "").strip())

        if not to_email and self.create_uid:
            to_email = ((self.create_uid.partner_id.email or "").strip()
                        or (self.create_uid.login or "").strip())

        if not to_email:
            _logger.warning("No tagger email for %s", self.name)
            return False

        subject = f"Tagging CLOSED [{self.name or ''}]"

        equipment_display = self.equipment_id.display_name if self.equipment_id else "-"
        sparepart_display = self.sparepart_product_id.display_name if self.sparepart_product_id else "-"
        sku = (self.sparepart_product_id.default_code if self.sparepart_product_id else "") or "-"

        closed_by = self.env.user.name or ""
        closed_by_email = self.env.user.login or ""
        closed_at = self._format_dt_id(fields.Datetime.now())
        open_url = self._tagging_open_url()

        body_html = f"""
        <p>Dear {escape(self.tagger_name or (self.user_id.name if self.user_id else "Tagger"))},</p>
        <p>Tagging kamu sudah ditutup (Closed) dengan detail:</p>
        <ul>
          <li><b>ID Tag:</b> {escape(self.name or "")}</li>
          <li><b>Status:</b> Closed</li>
          <li><b>Closed By:</b> {escape(closed_by)}{' &amp;&amp; ' + escape(closed_by_email) if closed_by_email else ''}</li>
          <li><b>Closed At:</b> {escape(closed_at)}</li>
          <li><b>Equipment:</b> {escape(equipment_display)}</li>
          <li><b>Sparepart:</b> {escape(sparepart_display)}</li>
          <li><b>SKU:</b> {escape(sku)}</li>
        </ul>
        <p><a href="{open_url}">Buka Tagging</a></p>
        """

        mail_vals = {
            "subject": subject,
            "body_html": body_html,
            "email_to": to_email,
            "email_from": "noreply-ops@cpp.co.id",
            "reply_to": closed_by_email or "noreply-ops@cpp.co.id",
        }

        self.env["mail.mail"].sudo().create(mail_vals)
        return True
    
    def action_set_open_wo(self):
        for rec in self:
            if rec.status == 'validated':
                if not rec.parent_equipment_id:
                    raise UserError('Superord Equipment harus diisi!')
                if not rec.equipment_id:
                    raise UserError('Equipment harus diisi!')
                if len(rec.wo_sparepart_ids) <= 0 or not rec.wo_sparepart_ids:
                    raise UserError("Silahkan lakukan Set Spare Part terlebih dahulu untuk melakukan Open-Wo")
                rec.is_locked = True
                rec.status = 'open_wo'
                
                if rec.close_start_date:
                    rec.close_start_date = False
                if rec.close_end_date:
                    rec.close_end_date = False
                if rec.close_description:
                    rec.close_description = False
                if rec.close_photo:
                    rec.close_photo = False
            else:
                raise UserError("Hanya bisa melakukan Open-WO pada status Validated saja!")