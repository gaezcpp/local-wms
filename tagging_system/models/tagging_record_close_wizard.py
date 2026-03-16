from odoo import models, fields, _
from odoo.exceptions import UserError

class TaggingRecordCloseWizard(models.TransientModel):
    _name = "tagging.record.close.wizard"
    _description = "Close Tagging Wizard"

    record_id = fields.Many2one("tagging.record", required=True, ondelete="cascade")

    equipment_id = fields.Many2one(
        "maintenance.equipment",
        string="Equipment",
        required=True,
        ondelete="restrict",
    )

    sparepart_product_id = fields.Many2one(
        "product.product",
        string="Sparepart",
        required=False,
        ondelete="restrict",
    )

    def action_confirm_close(self):
        self.ensure_one()
        rec = self.record_id

        if rec.status not in ("validated", "open_wo"):
            raise UserError(_("Close hanya bisa setelah Validated / Open - WO."))

        rec.write({
            "equipment_id": self.equipment_id.id,
            "sparepart_product_id": self.sparepart_product_id.id if self.sparepart_product_id else False,
            "equipment": self.equipment_id.display_name or self.equipment_id.name or "",
            "spare_part": self.sparepart_product_id.display_name if self.sparepart_product_id else "",
            "sku": (self.sparepart_product_id.default_code if self.sparepart_product_id else "") or "",
            "status": "closed",
        })

        rec._send_email_close_to_tagger()

        return {"type": "ir.actions.act_window_close"}

        