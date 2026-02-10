from odoo import models, fields, api

class StockQuant(models.Model):
    _inherit = 'stock.quant'
    
    inbound_date = fields.Datetime(string="Inbound Date", tracking=True)
    exp_group = fields.Datetime(string="Exp Group", tracking=True)
    
    @api.model
    def _gather(self, product_id, location_id, lot_id=None, package_id=None, owner_id=None, strict=False, qty=None):
        quants = super()._gather(
            product_id,
            location_id,
            lot_id=lot_id,
            package_id=package_id,
            owner_id=owner_id,
            strict=strict,
            qty=qty
        )
        # print(f"CONTEXTNYAA {self.env.context}")

        if self.env.context.get('uu_only'):
            quants = quants.filtered(lambda q: q.package_id and q.package_id.state == 'UU')
            print(f"QUANTSSSSS {quants}")

        return quants
