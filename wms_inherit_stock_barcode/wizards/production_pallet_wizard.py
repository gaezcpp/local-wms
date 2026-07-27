from odoo import models, fields, api

class ProductionPalletWizard(models.TransientModel):
    _name = 'production.pallet.wizard'
    _description = 'Konfirmasi Pallet Ke'

    picking_id = fields.Many2one('stock.picking', string="Picking")
    message = fields.Text(string="Pesan Konfirmasi", readonly=True)

    def action_confirm(self):
        self.ensure_one()
        return self.picking_id.with_context(pallet_ke_confirmed=True).button_validate()