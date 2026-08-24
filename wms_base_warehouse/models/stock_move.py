from odoo import models, fields, api
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare
import logging
_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = 'stock.move'
    
    sap_seq = fields.Integer(string="Seq", index=True)
    order_seq = fields.Integer(string="Order Seq")
    order_selection = fields.Selection([
        ('order', 'Order'),
        ('gratis', 'Gratis'),
    ], string="Order Selection", default='order')
    gratis_locked = fields.Boolean(compute='_compute_gratis_locked', string="Gratis Locked")

    # depends core-nya diulang di sini karena override compute mengganti daftar trigger
    @api.depends('origin', 'picking_id.name', 'scrap_id.name', 'location_dest_usage',
                 'is_inventory', 'inventory_name')
    def _compute_reference(self):
        """Isi reference dari origin untuk move yang tidak punya picking.

        _compute_reference core memakai picking_id.name, jadi move yang dibuat
        langsung tanpa picking (mis. konversi mat.to.mat) reference-nya kosong dan
        tidak bisa diisi lewat create vals karena selalu ditimpa compute ini.
        Hanya mengisi kalau core memang tidak menghasilkan apa-apa, jadi tidak
        pernah menimpa nilai yang sudah benar.
        """
        super()._compute_reference()
        for move in self:
            if not move.reference and move.origin:
                move.reference = move.origin

    def _compute_gratis_locked(self):
        for move in self:
            move.gratis_locked = move._is_gratis_locked()

    def _is_gratis_locked(self):
        self.ensure_one()
        if self.order_selection != 'gratis' or not self.sale_line_id:
            return False
        open_order_move = self.env['stock.move'].sudo().search([
            ('order_selection', '=', 'order'),
            ('product_id', '=', self.product_id.id),
            ('picking_id', '=', self.picking_id.id),
            ('state', 'not in', ('done', 'cancel')),
        ], limit=1)
        return bool(open_order_move)

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
            over = any(m.quantity != m.product_uom_qty for m in picking.move_ids)
            picking.over_delivery = over
    
    # UNTUK _ACTION_ASSIGN
    def _get_package_actual_qty(self, line):
        quants = line.package_id.quant_ids.filtered(lambda q: q.product_id == line.product_id)
        if line.lot_id:
            quants = quants.filtered(lambda q: q.lot_id == line.lot_id)
        return sum(quants.mapped('quantity'))

    def _get_pkg_reserved_qty_elsewhere(self, line):
        domain = [
            ('package_id', '=', line.package_id.id),
            ('product_id', '=', line.product_id.id),
            ('id', '!=', line.id),
            ('state', 'not in', ['done', 'cancel']),
        ]
        if line.lot_id:
            domain.append(('lot_id', '=', line.lot_id.id))
        return sum(self.env['stock.move.line'].sudo().search(domain).mapped('quantity'))

    def _force_full_pallet_line(self, line, actual_pkg_qty=None):
        rounding = line.product_id.uom_id.rounding
        if actual_pkg_qty is None:
            actual_pkg_qty = self._get_package_actual_qty(line)
        if float_compare(line.quantity, actual_pkg_qty, precision_rounding=rounding) >= 0:
            return False

        reserved_elsewhere = self._get_pkg_reserved_qty_elsewhere(line)
        available_for_line = actual_pkg_qty - reserved_elsewhere

        if float_compare(available_for_line, line.quantity, precision_rounding=rounding) <= 0:
            _logger.warning(
                f"[GRGI] full_pallet_line BLOCKED pkg={line.package_id.display_name} "
                f"reserved_elsewhere={reserved_elsewhere} actual={actual_pkg_qty} line={line.id}"
            )
            return True

        target_qty = min(available_for_line, actual_pkg_qty)
        _logger.info(
            f"[GRGI] full_pallet_line line={line.id} picking={line.move_id.picking_id.name} "
            f"qty {line.quantity}->{target_qty} actual_pkg={actual_pkg_qty}"
        )
        line.sudo().write({'quantity': target_qty})
        return float_compare(target_qty, actual_pkg_qty, precision_rounding=rounding) < 0

    def _force_full_pallet_dest_moves(self, move):
        need_reassign = self.env['stock.move'].sudo()
        touched_pickings = self.env['stock.picking'].sudo()
        dest_moves = move.move_dest_ids.filtered(lambda m: m.picking_id.picking_type_id.book_full_pallet)
        while dest_moves:
            for dest_move in dest_moves:
                lines = dest_move.move_line_ids.filtered('package_id')
                if not lines:
                    continue
                for line in lines:
                    if self._force_full_pallet_line(line):
                        need_reassign |= dest_move
                touched_pickings |= dest_move.picking_id
            dest_moves = dest_moves.move_dest_ids.filtered(lambda m: m.picking_id.picking_type_id.book_full_pallet)
        return need_reassign, touched_pickings

    def _book_full_pallet(self, moves_full_pallet, moves_uu):
        need_reassign = self.env['stock.move'].sudo()
        touched_pickings = self.env['stock.picking'].sudo()

        for move in moves_full_pallet:
            lines = move.move_line_ids.filtered('package_id')
            if not lines:
                continue

            rounding = move.product_id.uom_id.rounding
            actual_qty_by_line = {line: self._get_package_actual_qty(line) for line in lines}
            total_actual_qty = sum(actual_qty_by_line.values())
            has_partial = any(
                float_compare(line.quantity, actual_qty_by_line[line], precision_rounding=rounding) < 0
                for line in lines
            )

            if not has_partial or float_compare(move.quantity, total_actual_qty, precision_rounding=rounding) >= 0:
                continue

            touched_pickings |= move.picking_id
            for line in lines:
                if self._force_full_pallet_line(line, actual_qty_by_line[line]):
                    need_reassign |= move

            dest_need_reassign, dest_touched_pickings = self._force_full_pallet_dest_moves(move)
            need_reassign |= dest_need_reassign
            touched_pickings |= dest_touched_pickings

        if need_reassign:
            need_reassign._do_unreserve()
            need_reassign_uu = need_reassign & moves_uu
            need_reassign_others = need_reassign - moves_uu

            if need_reassign_others:
                super(StockMove, need_reassign_others)._action_assign()
            if need_reassign_uu:
                super(StockMove, need_reassign_uu.with_context(uu_only=True))._action_assign()

        # After bumping lines to a full pallet, quantities may now exactly
        # match the package contents, but core's _check_entire_pack() already
        # ran (in super()._action_assign(), before this method) against the
        # pre-bump partial quantities, so result_package_id was never set.
        # Re-run it here so entire-pack detection stays core behavior.
        pickings_to_check = touched_pickings.filtered(
            lambda p: p.move_line_ids.filtered(
                lambda ml: ml.package_id and not ml.result_package_id and ml.state not in ('done', 'cancel'),
            ),
        )
        if pickings_to_check:
            pickings_to_check._check_entire_pack()

    def _autofill_result_package(self, moves):
        for line in moves.move_line_ids.filtered(lambda l: l.package_id and not l.result_package_id):
            line.write({'result_package_id': line.package_id.id})

    def _clear_result_package(self, moves):
        lines = moves.move_line_ids.filtered('result_package_id')
        if lines:
            lines.write({'result_package_id': False})
            
    def _consolidate_sml_per_quant(self):
        for picking in self.mapped('picking_id'):
            sml_by_quant = {}
            lines_to_unlink = self.env['stock.move.line'].sudo()
            
            for line in picking.move_line_ids.filtered(lambda l: l.state not in ['done', 'cancel']):
                quant_key = (
                    line.move_id.id,
                    line.location_id.id, 
                    line.lot_id.id, 
                    line.package_id.id, 
                    line.owner_id.id
                )
                
                if quant_key not in sml_by_quant:
                    sml_by_quant[quant_key] = line
                else:
                    first_line = sml_by_quant[quant_key]
                    first_line.sudo().write({
                        'quantity': first_line.quantity + line.quantity
                    })
                    lines_to_unlink |= line
            
            if lines_to_unlink:
                lines_to_unlink.unlink()

    ## NOTE INI BELUM DITES DI QAS, TAPI NAIKIN AJA
    def _action_assign(self, **kwargs):

        bypass = self.env.context.get('bypass_adjust_demand', False)
        moves_uu = self.filtered(lambda m: m.picking_id.picking_type_id.uu_only)
        moves_full_pallet = self.filtered(lambda m: m.picking_id.picking_type_id.book_full_pallet and not bypass)
        moves_split_package = self.filtered(lambda m: m.picking_id.picking_type_id.split_package)
        moves_order_selection = self.filtered(lambda m: m.picking_id.picking_type_id.check_order_selection)

        gratis_locked_moves = self.env['stock.move']
        if moves_order_selection:
            gratis_locked_moves = self.filtered(lambda m: m._is_gratis_locked())
            if gratis_locked_moves:
                reserved_locked_moves = gratis_locked_moves.filtered(lambda m: m.state in ('partially_available', 'assigned'))
                if reserved_locked_moves:
                    reserved_locked_moves._do_unreserve()

        moves = self - gratis_locked_moves
        moves_uu = moves_uu - gratis_locked_moves
        moves_full_pallet = moves_full_pallet - gratis_locked_moves
        moves_normal = moves - moves_uu - moves_full_pallet
        moves_fp_only = moves_full_pallet - moves_uu

        res = True
        if moves_normal:
            res = super(StockMove, moves_normal)._action_assign(**kwargs) and res
        if moves_uu:
            res = super(StockMove, moves_uu.with_context(uu_only=True))._action_assign(**kwargs) and res
        if moves_fp_only:
            res = super(StockMove, moves_fp_only)._action_assign(**kwargs) and res
            
        self._consolidate_sml_per_quant()

        if moves_full_pallet:
            self._book_full_pallet(moves_full_pallet, moves_uu)

        moves_uu_to_set = moves_uu - moves_split_package
        if moves_uu_to_set:
            self._autofill_result_package(moves_uu_to_set)

        if moves_split_package:
            self._clear_result_package(moves_split_package)

        return res
    
    def _get_new_picking_values(self):
        vals = super()._get_new_picking_values()

        if self:
            first_move = self[0]
            picking = first_move.picking_id
            if picking:
                vals.update({
                    'po_sap_id': picking.po_sap_id.id,
                    'production_shift_id': picking.production_shift_id.id,
                })
                
            if first_move.sale_line_id and first_move.sale_line_id.order_id:
                vals['sloc_to'] = first_move.sale_line_id.order_id.sloc_to

        return vals
    
    def _prepare_procurement_values(self):
        self.ensure_one()
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
            
        if self.order_selection:
            values['order_selection'] = self.order_selection
        elif self.sale_line_id:
            values['order_selection'] = self.sale_line_id.order_selection
        elif self.purchase_line_id:
            values['order_selection'] = self.purchase_line_id.order_selection
            
        return values
    
    def _is_gr_prod(self, vals=None):
        picking = False
        prod_in_move_type = self.env['ir.config_parameter'].sudo().get_param('prod_in_move_type')
        
        if not prod_in_move_type:
            raise ValidationError("prod_in_move_type pada Operation Type belum disetting!")
            
        if vals and vals.get('picking_id'):
            picking = self.env['stock.picking'].browse(vals['picking_id'])
        elif self:
            picking = self[0].picking_id
            
        return picking and picking.picking_type_id.move_type_sap == str(prod_in_move_type)
    
    def _prepare_move_split_vals(self, qty):
        self.ensure_one()
        vals = super()._prepare_move_split_vals(qty)
        vals.update({
            'sale_line_id': self.sale_line_id.id if self.sale_line_id else False,
            'purchase_line_id': self.purchase_line_id.id if self.purchase_line_id else False,
            'sap_seq': self.sap_seq,
            'order_seq': self.order_seq,
            'order_selection': self.order_selection,
        })
        return vals
    
    def _action_done(self, **kwargs):
        res = super()._action_done(**kwargs)
        for move in res:
            for line in move.move_line_ids:
                if line.state == 'done' and line.stock_type:
                    domain = [
                        ('product_id', '=', line.product_id.id),
                        ('location_id', '=', line.location_dest_id.id),
                        ('package_id', '=', line.result_package_id.id if line.result_package_id else False), #AI
                    ]
                    if line.lot_id:
                        domain.append(('lot_id', '=', line.lot_id.id))

                    quants = self.env['stock.quant'].search(domain)
                    if quants:
                        quants.sudo().write({'stock_type': line.stock_type})

        self._unlock_gratis_siblings(res)
        return res

    def _unlock_gratis_siblings(self, done_moves):
        """When 'order' moves finish, re-check whether their sibling 'gratis' moves
        (same sale order + product) are now unlocked, and if so, try to reserve them
        right away instead of waiting for the next reservation pass."""
        order_moves_done = done_moves.filtered(
            lambda m: m.state == 'done' and m.order_selection == 'order' and m.sale_line_id
        )
        if not order_moves_done:
            return

        groups = {(m.sale_line_id.order_id.id, m.product_id.id) for m in order_moves_done}
        order_ids = [g[0] for g in groups]
        product_ids = [g[1] for g in groups]

        candidate_gratis_moves = self.env['stock.move'].sudo().search([
            ('order_selection', '=', 'gratis'),
            ('sale_line_id.order_id', 'in', order_ids),
            ('product_id', 'in', product_ids),
            ('state', 'in', ('confirmed', 'waiting', 'partially_available')),
        ])
        candidate_gratis_moves = candidate_gratis_moves.filtered(
            lambda m: (m.sale_line_id.order_id.id, m.product_id.id) in groups,
        )

        to_assign = candidate_gratis_moves.filtered(lambda m: not m._is_gratis_locked())
        if to_assign:
            to_assign._action_assign()

    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        self.ensure_one()
        res = super()._prepare_move_line_vals(quantity=quantity, reserved_quant=reserved_quant)
        
        is_production_only = self._is_gr_prod()
        
        if is_production_only:
            res['stock_type'] = 'QI'
        elif reserved_quant and reserved_quant.stock_type:
            res['stock_type'] = reserved_quant.stock_type

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
                'wh_category_id': matched_line.wh_category_id.id if matched_line.wh_category_id else False,
                'pallet_ke': matched_line.pallet_ke,
            }
            
            if not is_production_only and not res.get('stock_type') and matched_line.stock_type:
                update_vals['stock_type'] = matched_line.stock_type
                
            res.update(update_vals)

        return res