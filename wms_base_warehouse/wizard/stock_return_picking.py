from odoo import models, fields, api


class StockReturnPicking(models.TransientModel):
    _inherit = 'stock.return.picking'

    def _create_returns(self):
        res = super()._create_returns()

        picking = self.env['stock.picking'].browse(res.get('res_id'))
        if picking:
            picking.write({'synchronize_sap': False})

        return res