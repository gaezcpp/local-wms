from odoo import fields, models, _
from odoo.exceptions import UserError


class TaggingRecordRejectWizard(models.TransientModel):
    _name = "tagging.record.reject.wizard"
    _description = "Reject Tagging Wizard"

    record_id = fields.Many2one("tagging.record", required=True, ondelete="cascade")
    reason = fields.Text(string="Reason", required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        rec = self.record_id

        if rec.status != "open":
            raise UserError(_("Only Open record can be rejected."))

        rec.sudo().write({
            "reject_reason": self.reason,
            "status": "closed",
        })
        return {"type": "ir.actions.act_window_close"}
