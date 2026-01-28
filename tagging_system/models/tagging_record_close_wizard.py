from odoo import models, fields, _
from odoo.exceptions import UserError


class TaggingRecordCloseWizard(models.TransientModel):
    _name = "tagging.record.close.wizard"
    _description = "Close Tagging Wizard"

    record_id = fields.Many2one("tagging.record", required=True, ondelete="cascade")
    machine_bom_id = fields.Many2one("tagging.machine_bom", string="Equipment (Master)", required=True, ondelete="restrict")

    def action_confirm_close(self):
        self.ensure_one()
        rec = self.record_id

        if rec.status not in ("validated", "open_wo"):
            raise UserError(_("Close hanya bisa setelah Validated / Open - WO."))

        bom = self.machine_bom_id
        rec.write({
            "machine_bom_id": bom.id,
            "equipment": bom.unit_id.name if bom.unit_id else "",
            "spare_part": bom.spare_part_id.name if bom.spare_part_id else "",
            "sku": bom.sku or (bom.spare_part_id.sku if bom.spare_part_id else ""),
            "status": "closed",
        })
        return {"type": "ir.actions.act_window_close"}
