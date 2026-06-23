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
        # _logger.info("stock.quant _gather KEPANGGIL")
        print("stock.quant _gather KEPANGGIL")
        quants = super()._gather(
            product_id,
            location_id,
            lot_id=lot_id,
            package_id=package_id,
            owner_id=owner_id,
            strict=strict,
            qty=qty
        )
        # if self.env.context.get('uu_only'):
        #     quants = quants.filtered(
        #         lambda q: q.stock_type == 'UU' and (
        #             (q.package_id.yellow_tag == 'ready' and not q.package_id.is_reserved)
        #         )
        #     )
        if self.env.context.get('uu_only'):
            quants = quants.filtered(
                lambda q: q.stock_type == 'UU' and q.package_id and q.package_id.yellow_tag == 'ready' and not q.package_id.is_reserved
            )

        return quants
    
    def write(self, vals):
        old_values = {quant.id: quant.stock_type for quant in self}
        res = super().write(vals)
        if 'stock_type' in vals:
            self._log_stock_type_change(old_values)
            
        return res

    def _log_stock_type_change(self, old_values):
        for quant in self:
            old_type = old_values.get(quant.id)
            new_type = quant.stock_type
            if old_type != new_type and quant.package_id:
                message_body = f"Update Stock Type: Produk {quant.product_id.display_name} telah diubah dari {old_type or '-'} menjadi {new_type}."
                quant.package_id.message_post(body=message_body)
    
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
