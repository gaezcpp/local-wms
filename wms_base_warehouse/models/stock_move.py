from odoo import models, fields, api
import logging
_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = 'stock.move'
    
    sap_seq = fields.Integer(string="Seq")
    order_seq = fields.Integer(string="Order Seq")
    
    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        moves._update_over_delivery()
        return moves

    def write(self, vals):
        res = super().write(vals)
        if any(field in vals for field in ['quantity', 'product_uom_qty']):
            self._update_over_delivery()
        return res
    
    def _update_over_delivery(self):
        for move in self:
            picking = move.picking_id
            if not picking:
                continue

            over = False
            for m in picking.move_ids:
                if m.quantity != m.product_uom_qty:
                    over = True
                    break

            picking.over_delivery = over

    def _action_assign(self, **kwargs):
        moves_uu = self.filtered(lambda m: m.picking_id.picking_type_id.uu_only)
        moves_normal = self - moves_uu
        res = True
        _logger.info(f"MOVES NORMAL ATAU UU\nUU: {moves_uu}\nNormal: {moves_normal}")
        if moves_normal:
            res = super(StockMove, moves_normal)._action_assign()
        if moves_uu:
            res = super(StockMove, moves_uu.with_context(uu_only=True))._action_assign()
            # Untuk Picking UU Only otomatis terisi package/pallet
            for line in moves_uu.mapped('move_line_ids'):
                if line.package_id and not line.result_package_id:
                    _logger.info("MASUK PICKING ECERAN OTOMATIS ISI PACKAGE")
                    line.write({'result_package_id': line.package_id.id})
        return res
                    
    # ini untuk next transfer
    def _get_new_picking_values(self):
        vals = super()._get_new_picking_values()

        pickings = self.mapped('picking_id').filtered(lambda p: p)
        if pickings:
            picking = pickings[0]
            vals.update({
                'po_sap_id': picking.po_sap_id.id,
                'production_shift_id': picking.production_shift_id.id,
            })
            
        # kayaknya ga bener, jadinya pake related sloc_to
        if self.sale_line_id and self.sale_line_id.order_id:
            vals['sloc_to'] = self.sale_line_id.order_id.sloc_to

        return vals
    
    # prepare stock.move
    def _prepare_procurement_values(self):
        values = super(StockMove, self)._prepare_procurement_values()
        
        if self.sap_seq:
            values['sap_sequence'] = self.sap_seq
        elif self.sale_line_id:
            values['sap_sequence'] = self.sale_line_id.sap_sequence
        elif self.purchase_line_id:
            values['sap_sequence'] = self.purchase_line_id.sap_sequence
            
        if self.order_seq:
            values['order_seq'] = self.order_seq
        elif self.sale_line_id:
            values['order_seq'] = self.sale_line_id.order_seq
        elif self.purchase_line_id:
            values['order_seq'] = self.purchase_line_id.order_seq
            
        return values
    
    # def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
    #     res = super()._prepare_move_line_vals(quantity=quantity, reserved_quant=reserved_quant)
    #     if not self.move_orig_ids:
    #         return res

    #     origin_lines = self.move_orig_ids.mapped('move_line_ids').sorted('id')
    #     matched_line = False

    #     if reserved_quant:
    #         if reserved_quant.package_id:
    #             matched_line = origin_lines.filtered(
    #                 lambda l:
    #                     l.package_history_id.id == reserved_quant.package_id.id and
    #                     l.product_id == self.product_id
    #             )[:1]

    #         if not matched_line and reserved_quant.package_id:
    #             matched_line = origin_lines.filtered(
    #                 lambda l:
    #                     l.result_package_id.id == reserved_quant.package_id.id and
    #                     l.product_id == self.product_id
    #             )[:1]

    #         if not matched_line and reserved_quant.lot_id:
    #             matched_line = origin_lines.filtered(
    #                 lambda l:
    #                     l.lot_id.id == reserved_quant.lot_id.id and
    #                     l.product_id == self.product_id
    #             )[:1]

    #     if not matched_line:
    #         matched_line = origin_lines.filtered(
    #             lambda l: l.product_id == self.product_id
    #         )[:1]

    #     if not matched_line and origin_lines:
    #         matched_line = origin_lines[:1]

    #     if matched_line:
    #         res.update({
    #             'production_line_id': matched_line.production_line_id.id,
    #             'first_count': matched_line.first_count,
    #             'last_count': matched_line.last_count,
    #             'detail_text': matched_line.detail_text,
    #             'qty_packaging_sap': matched_line.qty_packaging_sap,
    #             'stock_type': matched_line.stock_type,
    #         })

    #     return res
    
    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        res = super()._prepare_move_line_vals(quantity=quantity, reserved_quant=reserved_quant)
        
        if reserved_quant and reserved_quant.stock_type:
            res['stock_type'] = reserved_quant.stock_type

        if not self.move_orig_ids:
            return res

        origin_lines = self.move_orig_ids.mapped('move_line_ids').sorted('id')
        matched_line = False

        if reserved_quant:
            if reserved_quant.package_id:
                matched_line = origin_lines.filtered(
                    lambda l:
                        l.package_history_id.id == reserved_quant.package_id.id and
                        l.product_id == self.product_id
                )[:1]

            if not matched_line and reserved_quant.package_id:
                matched_line = origin_lines.filtered(
                    lambda l:
                        l.result_package_id.id == reserved_quant.package_id.id and
                        l.product_id == self.product_id
                )[:1]

            if not matched_line and reserved_quant.lot_id:
                matched_line = origin_lines.filtered(
                    lambda l:
                        l.lot_id.id == reserved_quant.lot_id.id and
                        l.product_id == self.product_id
                )[:1]

        if not matched_line:
            matched_line = origin_lines.filtered(
                lambda l: l.product_id == self.product_id
            )[:1]

        if not matched_line and origin_lines:
            matched_line = origin_lines[:1]

        if matched_line:
            update_vals = {
                'production_line_id': matched_line.production_line_id.id,
                'first_count': matched_line.first_count,
                'last_count': matched_line.last_count,
                'detail_text': matched_line.detail_text,
                'qty_packaging_sap': matched_line.qty_packaging_sap,
                'stock_type': matched_line.stock_type,
            }
            
            # (Opsional) Jika stock_type gagal didapat dari reserved_quant, 
            # jadikan matched_line sebagai cadangan (fallback).
            if not res.get('stock_type') and matched_line.stock_type:
                update_vals['stock_type'] = matched_line.stock_type
                
            res.update(update_vals)

        return res