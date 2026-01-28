from odoo import models, fields, _, api
from io import BytesIO
import base64
from odoo.exceptions import UserError


class BarcodeTagging(models.Model):
    _name = "barcode.tagging"
    _description = "Master Barcode Tagging"
    _order = "barcode_code desc"

    barcode_code = fields.Char(string="Barcode Code", required=True, copy=False, readonly=True, index=True)

    plant_code = fields.Char()
    plant_name = fields.Char()

    business_unit_code = fields.Char(string="Business Area")
    business_unit_name = fields.Char()

    work_center = fields.Char()
    functional_location = fields.Char(required=True)

    active = fields.Boolean(default=True)
    qr_image = fields.Binary(string="QR Code", readonly=True)

    _sql_constraints = [
        ("barcode_code_uniq", "unique(barcode_code)", "Barcode Code harus unik!"),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if not vals.get("barcode_code"):
                vals["barcode_code"] = seq.next_by_code("barcode.tagging.code") or _("New")
        return super().create(vals_list)

    def action_generate_qr(self):
        ICP = self.env["ir.config_parameter"].sudo()
        base_url = (ICP.get_param("tagging.base_url") or ICP.get_param("web.base.url") or "").rstrip("/")
        if not base_url:
            raise UserError(_("Base URL belum diset. Set 'tagging.base_url' atau 'web.base.url'."))

        try:
            import qrcode
        except Exception:
            raise UserError(_("Library qrcode belum terpasang. Jalankan: pip install qrcode[pil]"))

        for rec in self:
            if not rec.barcode_code:
                continue

            # Portal pakai barcode_code (bukan equipment_code lagi)
            qr_url = f"{base_url}/tagging?barcode_code={rec.barcode_code}"

            qr = qrcode.QRCode(box_size=10, border=4)
            qr.add_data(qr_url)
            qr.make(fit=True)

            img = qr.make_image(fill_color="black", back_color="white")
            buff = BytesIO()
            img.save(buff, format="PNG")
            rec.write({"qr_image": base64.b64encode(buff.getvalue())})

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Success"),
                "message": _("QR berhasil dibuat."),
                "type": "success",
                "sticky": False,
            },
        }

    def action_download_qr(self):
        self.ensure_one()
        if not self.qr_image:
            raise UserError(_("QR belum ada. Generate dulu."))

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/barcode.tagging/{self.id}/qr_image?download=true&filename=QR_{self.barcode_code}.png",
            "target": "self",
        }
