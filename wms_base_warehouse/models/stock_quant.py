from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging
_logger =  logging.getLogger(__name__)
class StockQuant(models.Model):
    _inherit = 'stock.quant'
    
    exp_group = fields.Datetime(string="Exp Group")
    inbound_date = fields.Datetime(string="Inbound Date")
    stock_type = fields.Selection([
        ('QI', 'QI'),
        ('BLOCKED', 'BLOCKED'),
        ('UU', 'UU'),
    ], string="Stock Type", default='QI')
    
    # @api.model
    # def _gather(self, product_id, location_id, lot_id=None, package_id=None, owner_id=None, strict=False, qty=None):
    #     _logger.info("stock.quant _gather KEPANGGIL")
    #     quants = super()._gather(
    #         product_id,
    #         location_id,
    #         lot_id=lot_id,
    #         package_id=package_id,
    #         owner_id=owner_id,
    #         strict=strict,
    #         qty=qty
    #     )

    #     if self.env.context.get('uu_only'):
    #         quants = quants.filtered(lambda q: q.lot_id and q.lot_id.stock_type == 'UU')

    #     return quants
    
    @api.model
    def _gather(self, product_id, location_id, lot_id=None, package_id=None, owner_id=None, strict=False, qty=None):
        _logger.info("stock.quant _gather KEPANGGIL")
        quants = super()._gather(
            product_id,
            location_id,
            lot_id=lot_id,
            package_id=package_id,
            owner_id=owner_id,
            strict=strict,
            qty=qty
        )

        if self.env.context.get('uu_only'):
            quants = quants.filtered(
                lambda q: q.lot_id and any(
                    aft.stock_type == 'UU' and (aft.quantity > 0 or aft.bag_qty > 0)
                    for aft in q.lot_id.lot_aft_ids
                )
            )

        return quants
