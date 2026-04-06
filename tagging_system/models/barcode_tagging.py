from odoo import models, fields, _, api
from odoo.exceptions import UserError, ValidationError

from io import BytesIO
import base64
from urllib.parse import urlencode


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
    system_code = fields.Char(related="system_id.code", store=True, readonly=True)
    subsystem_code = fields.Char(related="subsystem_id.code", store=True, readonly=True)


    
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


    _sql_constraints = [
        ("barcode_code_uniq", "unique(barcode_code)", "Barcode Code harus unik!"),
    ]

    
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

            img = qr.make_image(fill_color="black", back_color="white")
            buff = BytesIO()
            img.save(buff, format="PNG")

            rec.qr_image = base64.b64encode(buff.getvalue())
            rec.qr_link = qr_url

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

    @api.onchange('subsystem_id')
    def _onchange_subsystem_set(self):
        for rec in self:
            if rec.subsystem_id:
                rec.write({'abc_indic': rec.subsystem_id.abc_indicator})
            else:
                rec.write({'abc_indic': False})