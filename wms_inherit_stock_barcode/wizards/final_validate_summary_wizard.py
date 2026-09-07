from odoo import fields, models


class FinalValidateSummaryWizard(models.TransientModel):
    _name = 'final.validate.summary.wizard'
    _description = 'Konfirmasi Validate Final'

    picking_id = fields.Many2one('stock.picking', string='Transfer', required=True)
    message = fields.Text(string='Summary', readonly=True)

    def action_confirm(self):
        self.ensure_one()
        return self.picking_id.with_context(final_summary_confirmed=True).button_validate()
