from odoo import models, fields, _, api
from odoo.exceptions import UserError, ValidationError

from io import BytesIO
import base64
from urllib.parse import urlencode
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image, ImageDraw, ImageFont = None, None, None


class BarcodeTagging(models.Model):
    _name = "barcode.tagging"
    _description = "Master Barcode Tagging"
    _order = "barcode_code desc"
    _rec_name = "barcode_code"

    barcode_code = fields.Char(
        string="Barcode Code",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: self.env["ir.sequence"].next_by_code("barcode.tagging.code") or _("New"),
    )
    display_name = fields.Char(compute="_compute_display_name", store=True)


    plant_id = fields.Many2one(
        "res.company",
        string="Plant",
        required=True,
        default=lambda self: self.env.company,
        ondelete="restrict",
    )

    company_id = fields.Many2one(
        "res.company",
        string="Company (Legacy)",
        related="plant_id",
        store=True,
        readonly=True,
    )

    plant_code = fields.Char(
        string="Plant Code",
        related="plant_id.company_registry",
        store=True,
        readonly=True,
    )

    plant_name = fields.Char(
        string="Plant Name",
        related="plant_id.name",
        store=True,
        readonly=True,
    )

 
    work_center_id = fields.Many2one(
        "maintenance.team",
        string="Work Center",
        ondelete="set null",
    )

    # =========================
    # REVISION FIELDS
    # =========================
    system_id = fields.Many2one(
        "tagging.system",
        string="System",
        required=True,
        ondelete="restrict",
    )

    subsystem_id = fields.Many2one(
        "tagging.subsystem",
        string="Sub System",
        ondelete="restrict",
    )
    system_code = fields.Char(string = "Sys Code", related="system_id.code", store=True, readonly=True)
    subsystem_code = fields.Char(string="Sub Code", related="subsystem_id.code", store=True, readonly=True)


    
    # legacy (tetap ada biar code/view lama gak pecah)
    functional_location = fields.Char(string="Functional Location (Legacy)")
    functional_location_name = fields.Char(string="System Name (Legacy)")
    abc_indic = fields.Char(string="Abc Indic")
    superord_functional_loc = fields.Char(string="Superord Functional Loc.")

    active = fields.Boolean(default=True)

    qr_image = fields.Binary(
        string="QR Code",
        readonly=True,
        attachment=True,
    )
    
    qr_link = fields.Text(string="QR Link", readonly=True)


    # _sql_constraints = [
    #     ("barcode_code_uniq", "unique(barcode_code)", "Barcode Code harus unik!"),
    # ]

    
    @api.onchange("system_id")
    def _onchange_system_id(self):
        self.subsystem_id = False
        return {
            "domain": {
                "subsystem_id": [("system_id", "=", self.system_id.id)] if self.system_id else [("id", "=", 0)]
            }
        }
        

    @api.depends("barcode_code", "plant_name", "system_id", "subsystem_id")
    def _compute_display_name(self):
        for rec in self:
            parts = [rec.barcode_code or ""]
            if rec.plant_name:
                parts.append(rec.plant_name)
            if rec.system_id:
                parts.append(rec.system_id.display_name)
            if rec.subsystem_id:
                parts.append(rec.subsystem_id.display_name)
            rec.display_name = " | ".join([p for p in parts if p])

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        System = self.env["tagging.system"].sudo()
        Subsystem = self.env["tagging.subsystem"].sudo()

        for vals in vals_list:
            vals.setdefault("barcode_code", seq.next_by_code("barcode.tagging.code") or _("New"))
            vals.setdefault("plant_id", self.env.company.id)

            # backward compatible dari legacy -> system_id
            if not vals.get("system_id"):
                legacy_sys = vals.get("functional_location_name") or vals.get("functional_location")
                if legacy_sys:
                    system = System.search([("name", "=", legacy_sys)], limit=1)
                    if not system:
                        system = System.create({"name": legacy_sys})
                    vals["system_id"] = system.id

            # backward compatible dari legacy -> subsystem_id (optional)
            if not vals.get("subsystem_id"):
                legacy_sub = vals.get("functional_location")
                if legacy_sub and vals.get("system_id"):
                    subsystem = Subsystem.search([
                        ("name", "=", legacy_sub),
                        ("system_id", "=", vals["system_id"]),
                    ], limit=1)
                    if not subsystem:
                        subsystem = Subsystem.create({
                            "name": legacy_sub,
                            "system_id": vals["system_id"],
                        })
                    vals["subsystem_id"] = subsystem.id

        return super().create(vals_list)

    # def action_generate_qr(self):
    #     ICP = self.env["ir.config_parameter"].sudo()
    #     base_url = (ICP.get_param("tagging.base_url") or ICP.get_param("web.base.url") or "").rstrip("/")
    #     if not base_url:
    #         raise UserError(_("Base URL belum diset. Set 'tagging.base_url' atau 'web.base.url'."))

    #     try:
    #         import qrcode
    #     except ImportError:
    #         raise UserError(_("Library qrcode belum terpasang. Jalankan: pip install qrcode[pil]"))
            
    #     if not Image:
    #         raise UserError(_("Library Pillow belum terpasang. Jalankan: pip install Pillow"))

    #     for rec in self:
    #         if not rec.id:
    #             raise ValidationError(_("Simpan record dulu sebelum Generate QR."))
    #         if not rec.system_id:
    #             raise ValidationError(_("System wajib diisi sebelum Generate QR."))
    #         if not rec.barcode_code:
    #             raise ValidationError(_("Barcode Code belum ada. Silakan save ulang."))

    #         qr_url = f"{base_url}/tagging?{urlencode({'barcode_code': rec.barcode_code})}"

    #         # 1. Generate core QR Code
    #         qr = qrcode.QRCode(box_size=15, border=4)
    #         qr.add_data(qr_url)
    #         qr.make(fit=True)
            
    #         # Convert ke RGB agar kompatibel dengan Pillow Canvas
    #         qr_img = qr.make_image(fill_color="black", back_color="white").convert('RGB')

    #         # 2. Siapkan Canvas A6
    #         # Resolusi standar cetak A6 pada 300 DPI adalah 1240 x 1748 pixel
    #         a6_width, a6_height = 1240, 1748
    #         canvas = Image.new('RGB', (a6_width, a6_height), 'white')

    #         # 3. Resize & Posisi QR Code di Canvas
    #         qr_img = qr_img.resize((800, 800), Image.Resampling.LANCZOS)
    #         qr_w, qr_h = qr_img.size
    #         x_qr = (a6_width - qr_w) // 2
    #         y_qr = 250  # Margin atas QR
    #         canvas.paste(qr_img, (x_qr, y_qr))

    #         # 4. Tambahkan Teks di Bawah QR
    #         draw = ImageDraw.Draw(canvas)
            
    #         # Coba load font TrueType, fallback ke default jika tidak ditemukan
    #         try:
    #             # Path font umum untuk server Linux (Ubuntu/Debian)
    #             font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60)
    #         except IOError:
    #             try:
    #                 font = ImageFont.truetype("arial.ttf", 60) # Fallback Windows
    #             except IOError:
    #                 font = ImageFont.load_default()

    #         sys_name = rec.system_id.name if rec.system_id else "-"
    #         sub_name = rec.subsystem_id.name if rec.subsystem_id else "-"
    #         text_str = f"{sys_name} | {sub_name}"

    #         # Kalkulasi posisi bounding box teks agar rata tengah (Center)
    #         text_bbox = draw.textbbox((0, 0), text_str, font=font)
    #         text_w = text_bbox[2] - text_bbox[0]
            
    #         x_txt = (a6_width - text_w) // 2
    #         y_txt = y_qr + qr_h + 100  # Jarak 100px di bawah gambar QR

    #         draw.text((x_txt, y_txt), text_str, font=font, fill="black")

    #         # 5. Konversi Canvas jadi Binary untuk Odoo
    #         buff = BytesIO()
    #         canvas.save(buff, format="PNG")

    #         rec.qr_image = base64.b64encode(buff.getvalue())
    #         rec.qr_link = qr_url

    #     return {
    #         "type": "ir.actions.client",
    #         "tag": "reload",
    #         "params": {
    #             "title": _("Success"),
    #             "message": _("QR A6 berhasil dibuat."),
    #             "type": "success",
    #             "sticky": False,
    #         },
    #     }
    
    def action_generate_qr(self):
        ICP = self.env["ir.config_parameter"].sudo()
        base_url = (ICP.get_param("tagging.base_url") or ICP.get_param("web.base.url") or "").rstrip("/")
        if not base_url:
            raise UserError(_("Base URL belum diset. Set 'tagging.base_url' atau 'web.base.url'."))

        try:
            import qrcode
        except Exception:
            raise UserError(_("Library qrcode belum terpasang. Jalankan: pip install qrcode[pil]"))

        try:
            from PIL import Image, ImageDraw, ImageFont
        except Exception:
            raise UserError(_("Library Pillow belum terpasang. Jalankan: pip install Pillow"))

        for rec in self:
            if not rec.id:
                raise ValidationError(_("Simpan record dulu sebelum Generate QR."))
            if not rec.system_id:
                raise ValidationError(_("System wajib diisi sebelum Generate QR."))
            if not rec.barcode_code:
                raise ValidationError(_("Barcode Code belum ada. Silakan save ulang."))

            qr_url = f"{base_url}/tagging?{urlencode({'barcode_code': rec.barcode_code})}"

            qr = qrcode.QRCode(box_size=10, border=4)
            qr.add_data(qr_url)
            qr.make(fit=True)

            qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

            # Susun label teks: system | subsystem
            system_name = rec.system_id.name if rec.system_id else ""
            subsystem_name = rec.subsystem_id.name if hasattr(rec, "subsystem_id") and rec.subsystem_id else ""
            if system_name and subsystem_name:
                label_text = f"{system_name} | {subsystem_name}"
            elif system_name:
                label_text = system_name
            else:
                label_text = ""

            if label_text:
                # Tambahkan padding bawah untuk teks
                padding = 40
                font_size = 20
                qr_width, qr_height = qr_img.size
                new_img = Image.new("RGB", (qr_width, qr_height + padding), "white")
                new_img.paste(qr_img, (0, 0))

                draw = ImageDraw.Draw(new_img)

                # Coba load font, fallback ke default jika tidak tersedia
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
                except Exception:
                    font = ImageFont.load_default()

                # Hitung posisi teks agar center
                try:
                    bbox = draw.textbbox((0, 0), label_text, font=font)
                    text_width = bbox[2] - bbox[0]
                except AttributeError:
                    # Pillow versi lama
                    text_width, _ = draw.textsize(label_text, font=font)

                text_x = (qr_width - text_width) // 2
                text_y = qr_height + (padding - font_size) // 2

                draw.text((text_x, text_y), label_text, fill="black", font=font)
                final_img = new_img
            else:
                final_img = qr_img

            buff = BytesIO()
            final_img.save(buff, format="PNG")

            rec.qr_image = base64.b64encode(buff.getvalue())
            rec.qr_link = qr_url

        return {
            "type": "ir.actions.client",
            "tag": "reload",
            "params": {
                "title": "Success",
                "message": "QR berhasil dibuat.",
                "type": "success",
                "sticky": False,
            },
        }

    # def action_generate_qr(self):
    #     ICP = self.env["ir.config_parameter"].sudo()
    #     base_url = (ICP.get_param("tagging.base_url") or ICP.get_param("web.base.url") or "").rstrip("/")
    #     if not base_url:
    #         raise UserError(_("Base URL belum diset. Set 'tagging.base_url' atau 'web.base.url'."))

    #     try:
    #         import qrcode
    #     except Exception:
    #         raise UserError(_("Library qrcode belum terpasang. Jalankan: pip install qrcode[pil]"))

    #     for rec in self:
    #         if not rec.id:
    #             raise ValidationError(_("Simpan record dulu sebelum Generate QR."))
    #         if not rec.system_id:
    #             raise ValidationError(_("System wajib diisi sebelum Generate QR."))
    #         if not rec.barcode_code:
    #             raise ValidationError(_("Barcode Code belum ada. Silakan save ulang."))

    #         qr_url = f"{base_url}/tagging?{urlencode({'barcode_code': rec.barcode_code})}"

    #         qr = qrcode.QRCode(box_size=10, border=4)
    #         qr.add_data(qr_url)
    #         qr.make(fit=True)

    #         img = qr.make_image(fill_color="black", back_color="white")
    #         buff = BytesIO()
    #         img.save(buff, format="PNG")

    #         rec.qr_image = base64.b64encode(buff.getvalue())
    #         rec.qr_link = qr_url

    #     return {
    #         "type": "ir.actions.client",
    #         "tag": "reload",
    #         "params": {
    #             "title": _("Success"),
    #             "message": _("QR berhasil dibuat."),
    #             "type": "success",
    #             "sticky": False,
    #         },
    #     }

    def action_download_qr(self):
        self.ensure_one()
        if not self.qr_image:
            raise UserError(_("QR belum ada. Generate dulu."))

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/barcode.tagging/{self.id}/qr_image?download=true&filename=QR_{self.barcode_code}.png",
            "target": "self",
        }

    @api.onchange('subsystem_id')
    def _onchange_subsystem_set(self):
        for rec in self:
            if rec.subsystem_id:
                rec.write({'abc_indic': rec.subsystem_id.abc_indicator})
            else:
                rec.write({'abc_indic': False})