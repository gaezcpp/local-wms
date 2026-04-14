from odoo import http
from odoo.http import request
from urllib.parse import quote
import base64
import logging

_logger = logging.getLogger(__name__)

MAX_FILES = 5
MAX_MB_PER_FILE = 5
ALLOWED_MIMES = {"image/jpeg", "image/png"}


class TaggingController(http.Controller):

    @http.route("/tagging", type="http", auth="user", website=True, methods=["GET"], csrf=False)
    def tagging_form(self, **kw):
        _logger.info("HIT /tagging controller uid=%s login=%s", request.env.user.id, request.env.user.login)

        barcode_code = (kw.get("barcode_code") or "").strip()
        error = kw.get("error")
        success = kw.get("success")

        barcode = False
        if barcode_code:
            barcode = request.env["barcode.tagging"].sudo().search(
                [("barcode_code", "=", barcode_code), ("active", "=", True)],
                limit=1
            )
            if not barcode and not error:
                error = "Barcode tidak valid. Silakan scan QR lokasi."

        # ==========================================================
        # SAFE RESOLVE company_id + plant_code + plant_name
        # ==========================================================
        company_id = False
        plant_code = ""
        plant_name = ""

        if barcode:
            # plant_id wajib (di model kamu required=True), tapi kita tetap amanin
            plant = barcode.plant_id or barcode.company_id

            company_id = plant.id if plant else False
            plant_code = (plant.company_registry or "") if plant else ""
            plant_name = barcode.plant_name or (plant.name if plant else "")

        # ==========================================================
        # OPSI A: Dropdown Department unik (diambil dari PIC aktif)
        # ==========================================================
        pics_all = request.env["tagging.pic"].sudo().search(
            [("active", "=", True)],
            order="email asc"
        )

        departments = pics_all.mapped("department_ids")
        departments = departments.sorted(key=lambda d: (d.name or "").lower())

        category_problems = request.env["category.problem"].sudo().search([
            ("active", "=", True),
            ('system_id', '=', barcode.system_id.id),
            ('subsystem_id', '=', barcode.subsystem_id.id),
        ], order="system_id asc, subsystem_id asc")

        values = {
            "barcode_code": barcode_code,
            "barcode": barcode,
            "company_id": company_id,
            "plant_code": plant_code,
            "plant_name": plant_name,
            "error": error,
            "success": success,
            "default_tagger_name": request.env.user.name or "",
            "default_tagger_email": request.env.user.email or "",
            "departments": departments,
            "category_problems": category_problems,
        }

        html = request.env["ir.ui.view"].sudo()._render_template("tagging_system.tagging_form", values)
        return request.make_response(html)



    @http.route("/tagging/submit", type="http", auth="user", website=True, methods=["POST"], csrf=True)
    def tagging_submit(self, **post):
        # 1) Validate barcode_code from QR
        barcode_code = (post.get("barcode_code") or "").strip()
        if not barcode_code:
            return request.redirect("/tagging?error=%s" % quote("Barcode tidak ditemukan. Silakan scan QR lokasi."))

        barcode = request.env["barcode.tagging"].sudo().search(
            [("barcode_code", "=", barcode_code), ("active", "=", True)],
            limit=1
        )
        if not barcode:
            return request.redirect("/tagging?error=%s" % quote("Barcode tidak valid. Silakan scan QR lokasi."))

        # 2) Validate uploads count
        files = request.httprequest.files.getlist("photos")
        if files and len(files) > MAX_FILES:
            return request.redirect(
                f"/tagging?error={quote(f'Maksimal {MAX_FILES} foto.')}&barcode_code={quote(barcode_code)}"
            )

        # 3) Validate required fields
        tagger_name = (post.get("tagger_name") or "").strip()
        tagger_email = (post.get("tagger_email") or "").strip()
        if not tagger_name:
            return request.redirect(
                f"/tagging?error={quote('Nama tagger wajib diisi.')}&barcode_code={quote(barcode_code)}"
            )
            
            
        if not tagger_email:
            return request.redirect(
            f"/tagging?error={quote('Email tagger wajib diisi.')}&barcode_code={quote(barcode_code)}"
        )
    

        # FIX UTAMA: terima semua kemungkinan nama field PIC dari template mana pun
        pic_hint = (
            (post.get("department_id") or "").strip()
            or (post.get("pic_id") or "").strip()
            or (post.get("pic_department_id") or "").strip()
            or (post.get("department") or "").strip()
        )
        if not pic_hint:
            return request.redirect(
                f"/tagging?error={quote('PIC wajib dipilih.')}&barcode_code={quote(barcode_code)}"
            )

        category_problem_id = (post.get("category_problem_id") or "").strip()
        if not category_problem_id:
            return request.redirect(
                f"/tagging?error={quote('Kategori masalah wajib dipilih.')}&barcode_code={quote(barcode_code)}"
            )

        # 4) Validate IDs (aman dari ValueError)
        dept_hint = (post.get("department_id") or "").strip()
        if not dept_hint:
            return request.redirect(
                f"/tagging?error={quote('PIC wajib dipilih.')}&barcode_code={quote(barcode_code)}"
            )

        try:
            dept_id = int(dept_hint)
        except Exception:
            return request.redirect(
                f"/tagging?error={quote('Department tidak valid.')}&barcode_code={quote(barcode_code)}"
            )

        dept = request.env["tagging.department"].sudo().browse(dept_id)
        if not dept.exists():
            return request.redirect(
                f"/tagging?error={quote('Department tidak valid.')}&barcode_code={quote(barcode_code)}"
            )

        # cari PIC yang punya department ini
        pic = request.env["tagging.pic"].sudo().search([
            ("active", "=", True),
            ("department_ids", "in", dept.id)
        ], limit=1)

        if not pic:
            return request.redirect(
                f"/tagging?error={quote('PIC untuk department ini belum diset.')}&barcode_code={quote(barcode_code)}"
            )

        pic_id_int = pic.id


        try:
            cp_id_int = int(category_problem_id)
        except Exception:
            return request.redirect(
                f"/tagging?error={quote('Kategori masalah tidak valid.')}&barcode_code={quote(barcode_code)}"
            )

        pic = request.env["tagging.pic"].sudo().browse(pic_id_int)
        if not pic.exists() or not pic.active:
            return request.redirect(
                f"/tagging?error={quote('PIC tidak valid.')}&barcode_code={quote(barcode_code)}"
            )

        cp = request.env["category.problem"].sudo().browse(cp_id_int)
        if not cp.exists() or not cp.active:
            return request.redirect(
                f"/tagging?error={quote('Kategori masalah tidak valid.')}&barcode_code={quote(barcode_code)}"
            )

        #  SAFE work center: handle beberapa kemungkinan field
        work_center_val = ""
        # kalau ada field m2o work_center_id
        if "work_center_id" in barcode._fields and barcode.work_center_id:
            work_center_val = barcode.work_center_id.display_name or barcode.work_center_id.name or ""
        # kalau ada field char work_center
        elif "work_center" in barcode._fields:
            work_center_val = barcode.work_center or ""

        # 5) Create tagging record
        rec_vals = {
            "user_id": request.env.user.id,
            "tagger_name": tagger_name,
            "tagger_email": tagger_email,

            "barcode_id": barcode.id,
            "pic_id": pic.id,
            "category_problem_id": cp.id,

            "plant_code": barcode.plant_code or "",
            "plant_name": barcode.plant_name or "",
       
            "work_center": work_center_val,
            "functional_location": barcode.functional_location or "",

            # snapshot kategori masalah dari barcode
            "problem_category": getattr(cp, "cat_masalah", "") or "",
            "problem_id": cp.problem_id.id or False,

            "description": (post.get("description") or "").strip(),
        }
        
        # =========================
        # ADD: system/subsystem snapshot dari barcode
        # =========================
        
        TagRec = request.env["tagging.record"]
        fields_rec = TagRec._fields

        if "system_id" in fields_rec and fields_rec["system_id"].type == "many2one":
            rec_vals["system_id"] = barcode.system_id.id if barcode.system_id else False

        if "sub_system_id" in fields_rec and fields_rec["sub_system_id"].type == "many2one":
            rec_vals["sub_system_id"] = barcode.subsystem_id.id if barcode.subsystem_id else False

        # kalau model tagging.record pakai field char snapshot:
        if "system_code" in request.env["tagging.record"]._fields:
            rec_vals["system_code"] = getattr(barcode, "system_code", "") or ""
            
        if barcode.subsystem_id and barcode.system_id and barcode.subsystem_id.system_id.id != barcode.system_id.id:
            rec_vals["sub_system_id"] = False

        if "subsystem_code" in request.env["tagging.record"]._fields:
            rec_vals["subsystem_code"] = getattr(barcode, "subsystem_code", "") or ""

        if "system_name" in request.env["tagging.record"]._fields:
            rec_vals["system_name"] = barcode.system_id.display_name if barcode.system_id else ""

        if "subsystem_name" in request.env["tagging.record"]._fields:
            rec_vals["subsystem_name"] = barcode.subsystem_id.display_name if barcode.subsystem_id else ""
        rec = request.env["tagging.record"].sudo().create(rec_vals)

        # 6) Save photos as attachments (aman)
        attachment_ids = []
        for f in files or []:
            mimetype = (getattr(f, "mimetype", "") or "").lower()
            if mimetype not in ALLOWED_MIMES:
                return request.redirect(
                    f"/tagging?error={quote('Format foto harus JPG/PNG.')}&barcode_code={quote(barcode_code)}"
                )

            # pastikan pointer di awal (kadang file obj sudah kebaca)
            try:
                f.stream.seek(0)
            except Exception:
                pass

            content = f.read() or b""
            if len(content) > MAX_MB_PER_FILE * 1024 * 1024:
                return request.redirect(
                    f"/tagging?error={quote(f'Ukuran foto maksimal {MAX_MB_PER_FILE}MB per file.')}&barcode_code={quote(barcode_code)}"
                )

            attachment = request.env["ir.attachment"].sudo().create({
                "name": getattr(f, "filename", None) or "photo",
                "type": "binary",
                "datas": base64.b64encode(content),
                "mimetype": mimetype,
                "res_model": "tagging.record",
                "res_id": rec.id,
            })
            attachment_ids.append(attachment.id)

        if attachment_ids and "attachment_ids" in rec._fields:
            rec.sudo().write({"attachment_ids": [(6, 0, attachment_ids)]})

        # 7) Back success
        return request.redirect(f"/tagging?success=1&barcode_code={quote(barcode_code)}")
    
    
    
