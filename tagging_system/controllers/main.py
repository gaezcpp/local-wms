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

        # master PIC (ambil yang aktif)
        pics = request.env["tagging.pic"].sudo().search(
            [("active", "=", True)],
            order="email asc"
        )

        # master category problem (ambil yang aktif)
        category_problems = request.env["category.problem"].sudo().search(
            [("active", "=", True)],
            order="sistem, sub_sistem, cat_masalah asc"
        )

        values = {
            "barcode_code": barcode_code,
            "barcode": barcode,
            "error": error,
            "success": success,
            "default_tagger_name": request.env.user.name or "",
            "pics": pics,
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
        if not tagger_name:
            return request.redirect(
                f"/tagging?error={quote('Nama tagger wajib diisi.')}&barcode_code={quote(barcode_code)}"
            )

        pic_id = (post.get("pic_id") or "").strip()
        if not pic_id:
            return request.redirect(
                f"/tagging?error={quote('PIC wajib dipilih.')}&barcode_code={quote(barcode_code)}"
            )

        category_problem_id = (post.get("category_problem_id") or "").strip()
        if not category_problem_id:
            return request.redirect(
                f"/tagging?error={quote('Kategori masalah wajib dipilih.')}&barcode_code={quote(barcode_code)}"
            )

        # (opsional) pastikan id valid
        pic = request.env["tagging.pic"].sudo().browse(int(pic_id))
        if not pic.exists() or not pic.active:
            return request.redirect(
                f"/tagging?error={quote('PIC tidak valid.')}&barcode_code={quote(barcode_code)}"
            )

        cp = request.env["category.problem"].sudo().browse(int(category_problem_id))
        if not cp.exists() or not cp.active:
            return request.redirect(
                f"/tagging?error={quote('Kategori masalah tidak valid.')}&barcode_code={quote(barcode_code)}"
            )

        # 4) Create tagging record
        rec_vals = {
            "user_id": request.env.user.id,
            "tagger_name": tagger_name,

            "barcode_id": barcode.id,          # pastikan field ini ada di tagging.record
            "pic_id": pic.id,                  # pastikan field ini ada di tagging.record (Many2one tagging.pic)
            "category_problem_id": cp.id,      # pastikan field ini ada di tagging.record (Many2one category.problem)

            # snapshot dari barcode
            "plant_code": barcode.plant_code or "",
            "plant_name": barcode.plant_name or "",
            "business_unit_code": barcode.business_unit_code or "",
            "business_unit_name": barcode.business_unit_name or "",
            "work_center": barcode.work_center or "",
            "functional_location": barcode.functional_location or "",

            # snapshot kategori masalah juga kalau kamu masih mau simpan string (optional)
            "problem_category": cp.cat_masalah or "",

            "description": (post.get("description") or "").strip(),
        }

        rec = request.env["tagging.record"].sudo().create(rec_vals)

        # 5) Save photos as attachments
        attachment_ids = []
        for f in files or []:
            mimetype = f.mimetype or ""
            if mimetype not in ALLOWED_MIMES:
                return request.redirect(
                    f"/tagging?error={quote('Format foto harus JPG/PNG.')}&barcode_code={quote(barcode_code)}"
                )

            content = f.read() or b""
            if len(content) > MAX_MB_PER_FILE * 1024 * 1024:
                return request.redirect(
                    f"/tagging?error={quote(f'Ukuran foto maksimal {MAX_MB_PER_FILE}MB per file.')}&barcode_code={quote(barcode_code)}"
                )

            attachment = request.env["ir.attachment"].sudo().create({
                "name": f.filename or "photo",
                "type": "binary",
                "datas": base64.b64encode(content),
                "mimetype": mimetype,
                "res_model": "tagging.record",
                "res_id": rec.id,
            })
            attachment_ids.append(attachment.id)

        if attachment_ids:
            rec.sudo().write({"attachment_ids": [(6, 0, attachment_ids)]})

        # 6) Back
        return request.redirect(f"/tagging?success=1&barcode_code={quote(barcode_code)}")
