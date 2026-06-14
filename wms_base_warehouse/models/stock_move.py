from odoo import models, fields, api
from odoo.exceptions import ValidationError
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
        # Kelompokkan berdasarkan tipe operasi
        moves_uu = self.filtered(lambda m: m.picking_id.picking_type_id.uu_only)
        moves_full_pallet = self.filtered(lambda m: m.picking_id.picking_type_id.book_full_pallet)
        
        # Gabungkan semua dokumen yang butuh perlakuan Full Pallet (Step 1, 2, dan 3)
        moves_to_check_full = moves_uu | moves_full_pallet
        
        # Sisanya adalah dokumen normal (Step 4 / GI)
        moves_normal = self - moves_to_check_full
        
        res = True
        
        # 1. Jalankan Assign bawaan Odoo sesuai jalurnya masing-masing
        if moves_normal:
            res = super(StockMove, moves_normal)._action_assign()
        if moves_uu:
            res = super(StockMove, moves_uu.with_context(uu_only=True))._action_assign()
        
        # Jalankan assign untuk book_full_pallet yang bukan uu_only (Step 2 & 3)
        moves_fp_only = moves_full_pallet - moves_uu
        if moves_fp_only:
            res = super(StockMove, moves_fp_only)._action_assign()

        need_reassign = self.env['stock.move'].sudo()
        
        # 2. Logika Full Pallet untuk Step 1, 2, dan 3
        for move in moves_to_check_full:
            total_actual_pkg_qty = 0
            has_partial = False
            
            for line in move.move_line_ids:
                if line.package_id:
                    actual_pkg_qty = sum(line.package_id.quant_ids.filtered(
                        lambda q: q.product_id == line.product_id
                    ).mapped('quantity'))
                    
                    total_actual_pkg_qty += actual_pkg_qty
                    
                    if line.quantity < actual_pkg_qty:
                        has_partial = True
                        
            if has_partial and move.product_uom_qty < total_actual_pkg_qty:
                # Update target kuantitas dokumen saat ini
                move.product_uom_qty = total_actual_pkg_qty
                need_reassign |= move
                
                # -------------------------------------------------------------
                # 3. PROPAGASI BERSYARAT (HANYA SAMPAI STEP 3)
                # -------------------------------------------------------------
                dest_moves = move.move_dest_ids
                while dest_moves:
                    # Filter: Apakah dokumen pelanjutnya ini Checker/Load?
                    valid_dest = dest_moves.filtered(
                        lambda m: m.picking_id.picking_type_id.uu_only or m.picking_id.picking_type_id.book_full_pallet
                    )
                    
                    if valid_dest:
                        # Jika ya, paksa naikkan kuantitasnya jadi Full Pallet
                        valid_dest.sudo().write({'product_uom_qty': total_actual_pkg_qty})
                        dest_moves = valid_dest.mapped('move_dest_ids')
                    else:
                        # Jika kita menabrak Step 4 (GI Outgoing) yang tidak ada centang
                        # uu_only atau book_full_pallet, HENTIKAN PENULARAN DI SINI!
                        break
                
        # 4. Re-assign untuk menyedot sisa stok yang baru saja dinaikkan
        if need_reassign:
            need_reassign_uu = need_reassign & moves_uu
            need_reassign_others = need_reassign - moves_uu
            
            if need_reassign_others:
                super(StockMove, need_reassign_others)._action_assign()
            if need_reassign_uu:
                super(StockMove, need_reassign_uu.with_context(uu_only=True))._action_assign()

        # 5. Pengisian Otomatis Result Package KHUSUS Step 1 (uu_only)
        for line in moves_uu.mapped('move_line_ids'):
            if line.package_id and not line.result_package_id:
                line.write({'result_package_id': line.package_id.id})
                
        return res
    
    # def _action_assign(self, **kwargs):
    #     moves_uu = self.filtered(lambda m: m.picking_id.picking_type_id.uu_only)
    #     moves_full_pallet = self.filtered(lambda m: m.picking_id.picking_type_id.book_full_pallet)
    #     moves_normal = self - moves_uu
    #     res = True
    #     _logger.info(f"MOVES NORMAL ATAU UU\nUU: {moves_uu}\nNormal: {moves_normal}")
    #     if moves_normal:
    #         res = super(StockMove, moves_normal)._action_assign()
    #     if moves_uu and not moves_full_pallet:
    #         res = super(StockMove, moves_uu.with_context(uu_only=True))._action_assign()
    #         need_reassign = self.env['stock.move']
    #         for move in moves_uu:
    #             total_actual_pkg_qty = 0
    #             has_partial = False
    #             for line in move.move_line_ids:
    #                 if line.package_id:
    #                     actual_pkg_qty = sum(line.package_id.quant_ids.filtered(lambda q: q.product_id == line.product_id).mapped('quantity'))
    #                     total_actual_pkg_qty += actual_pkg_qty
    #                     if line.quantity < actual_pkg_qty:
    #                         has_partial = True
                            
    #             if has_partial and move.product_uom_qty < total_actual_pkg_qty:
    #                 move.product_uom_qty = total_actual_pkg_qty
    #                 need_reassign |= move
                    
    #         if need_reassign:
    #             super(StockMove, need_reassign.with_context(uu_only=True))._action_assign()
            
    #         for line in moves_uu.mapped('move_line_ids'):
    #             if line.package_id and not line.result_package_id:
    #                 line.write({'result_package_id': line.package_id.id})
    #     return res
                    
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
    
    def _is_gr_prod(self, vals=None):
        picking = False
        prod_in_move_type = self.env['ir.config_parameter'].sudo().get_param('prod_in_move_type')
        
        if not prod_in_move_type:
            raise ValidationError("prod_in_move_type pada Operation Type belum disetting!")
            
        if vals and vals.get('picking_id'):
            picking = self.env['stock.picking'].browse(vals['picking_id'])
        elif self.picking_id:
            picking = self.picking_id
            
        return picking and picking.picking_type_id.move_type_sap == str(prod_in_move_type)
    
    def _action_done(self, **kwargs):
        res = super()._action_done(**kwargs)
        for move in res:
            for line in move.move_line_ids:
                if line.state == 'done' and line.stock_type:
                    domain = [
                        ('product_id', '=', line.product_id.id),
                        ('location_id', '=', line.location_dest_id.id),
                    ]
                    if line.lot_id:
                        domain.append(('lot_id', '=', line.lot_id.id))
                    if line.result_package_id:
                        domain.append(('package_id', '=', line.result_package_id.id))
                    
                    quants = self.env['stock.quant'].search(domain)
                    if quants:
                        quants.sudo().write({'stock_type': line.stock_type})
                        
        return res
    
    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        res = super()._prepare_move_line_vals(quantity=quantity, reserved_quant=reserved_quant)
        
        is_production_only = self._is_gr_prod()
        
        # 1. Pengecekan IF-ELSE yang lebih rapi dan bersih
        if is_production_only:
            res['stock_type'] = 'QI'
        elif reserved_quant and reserved_quant.stock_type:
            res['stock_type'] = reserved_quant.stock_type

        # 2. Lanjut ke pengecekan origin (dokumen hulu)
        if not self.move_orig_ids:
            return res

        origin_lines = self.move_orig_ids.mapped('move_line_ids').sorted('id')
        matched_line = False

        if reserved_quant:
            if reserved_quant.package_id:
                matched_line = origin_lines.filtered(
                    lambda l: l.package_history_id.id == reserved_quant.package_id.id and l.product_id == self.product_id
                )[:1]

            if not matched_line and reserved_quant.package_id:
                matched_line = origin_lines.filtered(
                    lambda l: l.result_package_id.id == reserved_quant.package_id.id and l.product_id == self.product_id
                )[:1]

            if not matched_line and reserved_quant.lot_id:
                matched_line = origin_lines.filtered(
                    lambda l: l.lot_id.id == reserved_quant.lot_id.id and l.product_id == self.product_id
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
            }
            
            if not is_production_only and not res.get('stock_type') and matched_line.stock_type:
                update_vals['stock_type'] = matched_line.stock_type
                
            res.update(update_vals)

        return res