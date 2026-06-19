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
    ], string="Stock Type")
    
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
        
        # Jauh lebih cepat: Filter langsung dari stock_type milik stock.quant
        if self.env.context.get('uu_only'):
            quants = quants.filtered(
                lambda q: q.stock_type == 'UU' and q.quantity > 0 and (
                    not q.package_id or (q.package_id.yellow_tag == 'ready' and not q.package_id.is_reserved)
                )
            )

        return quants
    
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
    #         quants = quants.filtered(
    #             lambda q: (
    #                 q.lot_id and any(
    #                     aft.stock_type == 'UU' and (aft.quantity > 0 or aft.bag_qty > 0)
    #                     for aft in q.lot_id.lot_aft_ids
    #                 )
    #             ) and (
    #                 q.package_id and q.package_id.yellow_tag == 'ready' and not q.package_id.is_reserved
    #             )
    #         )

    #     return quants
