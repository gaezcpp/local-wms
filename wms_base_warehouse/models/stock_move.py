import math
from collections import defaultdict

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

    def _action_confirm(self, merge=True, merge_into=False, create_proc=True):
        """Gabungkan move order+gratis produk yang sama jadi satu move survivor
        di setiap picking type SELAIN Final (`picking_type_id.move_type_sap`
        falsy) DAN SELAIN langkah sesudah Final (Good Issue, `code ==
        'outgoing'`), sebelum masing-masing sempat mengalir ke `super()` dan
        memicu rantai MTO-nya sendiri secara terpisah.

        Odoo membangun rantai MTO dari belakang: mengonfirmasi move
        SO/PO-line memicu `stock.rule._run_pull()` yang langsung
        mengonfirmasi move langkah sebelumnya juga (`_action_confirm()` ->
        `_run_pull()` -> `moves._action_confirm()`). Karena baris order dan
        baris gratis masing-masing membentuk prokurmennya sendiri, kalau
        keduanya dibiarkan lewat `super()` apa adanya, PICK/CO/Load akan
        punya DUA rantai paralel. Non-survivor karena itu TIDAK PERNAH boleh
        sampai ke `super()` -- ia dibatalkan di sini, dan `super()` hanya
        dipanggil untuk survivor (atau move yang memang tidak punya
        pasangan). Final sengaja dikecualikan: kedua move Final (order/
        gratis) tetap dua move terpisah, di-reallocate lewat
        `_reallocate_gratis_final_demand()` saat Load selesai. Lihat plan
        'groovy-hatching-pelican' bagian 1.

        Good Issue (mis. `GI-LOCO`/`GI-FRNC`/`GI-STO-*`) HARUS ikut
        dikecualikan walau `move_type_sap`-nya sendiri falsy: rantai MTO
        dibangun dari Customer ke belakang, jadi move Good Issue order+
        gratis DIBUAT DAN DIKONFIRMASI LEBIH DULU daripada move Final --
        kalau Good Issue ikut digabung, gratis-nya sudah dibatalkan sebelum
        `_run_pull()` sempat membuat move Final-nya sendiri, dan Final
        berakhir cuma satu move (bukan dua) sejak awal. Semua Good Issue di
        warehouse ini bertipe `code == 'outgoing'`, sedangkan Final dan
        semua langkah sebelumnya (PICK/CO/Load) `code == 'internal'`.
        """
        mergeable = self.filtered(
            lambda m: m.state == 'draft'
            and m.order_selection
            and not m.picking_type_id.move_type_sap
            and m.picking_type_id.code != 'outgoing'
            and (m.sale_line_id or m.purchase_line_id)
        )
        to_cancel = self._merge_gratis_moves(mergeable) if mergeable else self.env['stock.move']

        moves_to_confirm = self - to_cancel
        if not moves_to_confirm:
            return moves_to_confirm
        return super(StockMove, moves_to_confirm)._action_confirm(
            merge=merge, merge_into=merge_into, create_proc=create_proc,
        )

    def _merge_gratis_moves(self, moves):
        """Untuk tiap move di `moves`, cari sibling terbuka (belum done/cancel)
        dengan product/picking_type/lokasi/order yang sama DAN
        `order_selection` KEBALIKANNYA, gabungkan qty-nya ke satu survivor,
        lalu batalkan sisanya.

        Survivor: move `order_selection == 'order'` menang; kalau seri, id
        terkecil. `move_dest_ids` sibling yang dibatalkan dipindah ke
        survivor supaya langkah berikutnya (yang sudah/akan dibuat oleh
        salah satu dari keduanya) tetap tertaut.

        Sibling WAJIB `order_selection` kebalikan `move` -- bukan sekadar
        "co-located terbuka apa saja". Tanpa syarat ini, move backorder yang
        dibuat `_action_done()` saat qty scan kurang dari demand (operation
        type `create_backorder='always'`, mis. PICK/CO) ikut kena: move sisa
        itu SELALU mewarisi `order_selection` PARENT-nya (sama-sama 'order',
        gratis-nya sudah lama melebur), tapi lolos ke `_action_confirm()`
        lewat proses backorder core -- kalau ikut disamakan sebagai
        "sibling", ia bukan cuma dibatalkan sebelum sempat jadi picking
        backorder yang semestinya, tapi qty-nya juga ikut ditambahkan
        kembali ke demand move asal yang SUDAH benar direduksi core jadi
        sebesar qty yang benar-benar di-scan -- korupsi ganda. Move
        order+gratis asli SELALU beda `order_selection`, jadi syarat ini
        tidak pernah menolak pasangan yang sah.

        Return recordset move yang dibatalkan -- pemanggil WAJIB
        mengecualikannya dari `super()._action_confirm()`.
        """
        StockMove = self.env['stock.move'].sudo()
        to_cancel = self.env['stock.move']

        for move in moves:
            if move.id in to_cancel.ids or move.state != 'draft':
                continue

            order = move.sale_line_id.order_id or move.purchase_line_id.order_id
            if not order:
                continue

            domain = [
                ('id', '!=', move.id),
                ('product_id', '=', move.product_id.id),
                ('picking_type_id', '=', move.picking_type_id.id),
                ('location_id', '=', move.location_id.id),
                ('location_dest_id', '=', move.location_dest_id.id),
                ('state', 'not in', ('done', 'cancel')),
                ('order_selection', '!=', move.order_selection),
            ]
            if move.sale_line_id:
                domain.append(('sale_line_id.order_id', '=', order.id))
            else:
                domain.append(('purchase_line_id.order_id', '=', order.id))

            siblings = (StockMove.search(domain) - to_cancel)
            if not siblings:
                continue

            group = move | siblings
            gratis_moves = group.filtered(lambda m: m.order_selection == 'gratis')
            if len(gratis_moves) > 1:
                _logger.warning(
                    "[GRATIS-MERGE] lebih dari satu move 'gratis' untuk order %s "
                    "produk %s: %s -- tidak sesuai model bisnis, digabung apa "
                    "adanya",
                    order.id, move.product_id.display_name, gratis_moves.ids,
                )

            order_moves = group.filtered(lambda m: m.order_selection == 'order')
            survivor = (order_moves or group).sorted('id')[0]
            non_survivors = group - survivor

            rounding = survivor.product_id.uom_id.rounding or 0.01
            total_qty = sum(group.mapped('product_uom_qty'))
            if float_compare(total_qty, survivor.product_uom_qty, precision_rounding=rounding) != 0:
                survivor.product_uom_qty = total_qty

            dest_ids = non_survivors.mapped('move_dest_ids')
            if dest_ids:
                survivor.move_dest_ids |= dest_ids

            non_survivors.write({'state': 'cancel'})
            to_cancel |= non_survivors

        return to_cancel

    ## NOTE INI BELUM DITES DI QAS, TAPI NAIKIN AJA
    def _action_assign(self, **kwargs):

        bypass = self.env.context.get('bypass_adjust_demand', False)
        moves_uu = self.filtered(lambda m: m.picking_id.picking_type_id.uu_only)
        moves_full_pallet = self.filtered(lambda m: m.picking_id.picking_type_id.book_full_pallet and not bypass)
        moves_split_package = self.filtered(lambda m: m.picking_id.picking_type_id.split_package)

        moves = self
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
        self._propagate_stock_type_to_quants(res.move_line_ids)
        self._reallocate_gratis_final_demand(res)
        return res

    def _propagate_stock_type_to_quants(self, move_lines):
        """Salin stock_type move line ke quant tujuannya.

        Dulu satu `search()` per move line; sekarang satu search untuk seluruh
        batch lalu dicocokkan di memori, dan penulisannya dikelompokkan per
        stock_type sehingga jumlah query tidak lagi tumbuh per baris.
        """
        lines = move_lines.filtered(lambda l: l.state == 'done' and l.stock_type)
        if not lines:
            return

        quants = self.env['stock.quant'].search([
            ('product_id', 'in', lines.product_id.ids),
            ('location_id', 'in', lines.location_dest_id.ids),
        ])
        if not quants:
            return

        quants_by_key = defaultdict(lambda: self.env['stock.quant'])
        for quant in quants:
            key = (quant.product_id.id, quant.location_id.id, quant.package_id.id or False)
            quants_by_key[key] |= quant

        # Baris GR produksi dipisahkan karena `stock_type`-nya TIDAK diwarisi
        # dari quant mana pun: `stock.move.line._apply_gr_prod_stock_type()`
        # memasangnya eksplisit QI. Pembedaan ini dipakai
        # `stock.quant._log_stock_type_change()` untuk memilih bunyi pesan
        # chatter -- jangan sampai chatter GR mengklaim "diwarisi dari quant
        # asal" padahal tidak ada quant asal yang dibaca.
        prod_in_move_type = self.env['ir.config_parameter'].sudo().get_param('prod_in_move_type')
        gr_prod_lines = lines.filtered(
            lambda l: l.picking_id.picking_type_id.move_type_sap == str(prod_in_move_type)
        ) if prod_in_move_type else self.env['stock.move.line']

        by_stock_type = defaultdict(lambda: self.env['stock.quant'])
        for line in lines:
            key = (
                line.product_id.id,
                line.location_dest_id.id,
                line.result_package_id.id or False,
            )
            candidates = quants_by_key.get(key)
            if not candidates:
                continue
            if line.lot_id:
                candidates = candidates.filtered(lambda q, lot=line.lot_id: q.lot_id == lot)
            if candidates:
                by_stock_type[(line.stock_type, line in gr_prod_lines)] |= candidates

        for (stock_type, is_gr_prod), target_quants in by_stock_type.items():
            # Quant yang stock_type-nya sudah benar tidak perlu ditulis ulang:
            # write-nya memicu _sync_to_lot_aft() dan message_post pada package.
            changed = target_quants.filtered(lambda q, st=stock_type: q.stock_type != st)
            if changed:
                changed.sudo().with_context(
                    stock_type_from_source_quant=not is_gr_prod,
                ).write({'stock_type': stock_type})

    def _reallocate_gratis_final_demand(self, done_moves):
        """Setelah move yang memasok pasangan order/gratis selesai (Final,
        atau langkah-langkah SESUDAHNYA seperti Good Issue), hitung ulang
        demand pasangan move tujuan itu -- lihat plan 'groovy-hatching-pelican'
        bagian 2.

        PICK/CO/Load digabung jadi satu move oleh `_action_confirm()`, tapi
        Final dan setiap langkah `code == 'outgoing'` sesudahnya (Good Issue)
        SENGAJA dikecualikan dari penggabungan itu, jadi tiap langkah itu
        tetap punya dua move (order/gratis) sejak awal. Reallocation ini
        TIDAK dibatasi hanya pada langkah Final: dia berjalan pada SETIAP
        move yang selesai dan tujuannya adalah pasangan order/gratis, supaya
        koreksi qty ikut merambat ke Good Issue (dan langkah apa pun
        sesudahnya) -- kalau tidak, Good Issue tetap menagih demand asli
        SO-line (mis. 100/5) padahal yang benar-benar sampai cuma hasil
        split Final (97/3), dan berakhir macet `partially_available`
        selamanya.

        Penting: di Load, SATU move gabungan (hasil merge) punya
        `move_dest_ids` yang LANGSUNG berisi pasangan order+gratis Final
        (di-union waktu merge, lihat `_merge_gratis_moves`). Tapi di Final
        sendiri, order-move dan gratis-move-nya TIDAK pernah digabung, jadi
        keduanya done TERPISAH dan masing-masing `move_dest_ids` cuma
        berisi SATU move Good-Issue (pasangannya sendiri) -- pasangannya
        cuma kelihatan kalau move_dest_ids KEDUA move digabung dulu. Karena
        itu `feeding_moves` dikelompokkan dulu per (product, order) sebelum
        mengumpulkan tujuannya, supaya kedua bentuk itu (satu move gabungan
        vs sepasang move terpisah) sama-sama menghasilkan pasangan tujuan
        yang lengkap.

        `_reallocate_gratis_final_pair()` sendiri yang menyaring "pasangan
        order/gratis" itu (persis 2 move, order_selection berbeda), jadi
        move tujuan yang bukan pasangan (mis. CO/Load hasil merge, cuma 1
        move) otomatis no-op di sana. Dihitung KUMULATIF setiap kali dari
        `move_orig_ids` supaya backorder/validasi parsial berulang tetap
        konvergen, bukan menumpuk.
        """
        feeding_moves = done_moves.filtered(lambda m: m.state == 'done' and m.move_dest_ids)
        if not feeding_moves:
            return

        groups = defaultdict(lambda: self.env['stock.move'])
        for move in feeding_moves:
            order = move.sale_line_id.order_id or move.purchase_line_id.order_id
            groups[(move.product_id.id, order.id if order else False)] |= move

        seen_pairs = set()
        for group in groups.values():
            dest_moves = group.mapped('move_dest_ids')
            if not dest_moves:
                continue

            by_picking = defaultdict(lambda: self.env['stock.move'])
            for dest_move in dest_moves:
                by_picking[dest_move.picking_id.id] |= dest_move

            for finals_group in by_picking.values():
                key = tuple(sorted(finals_group.ids))
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                self._reallocate_gratis_final_pair(finals_group)

    def _reallocate_gratis_final_pair(self, finals_group):
        """Tulis ulang `quantity` (qty aktual/reserved) pasangan move Final
        order/gratis -- BUKAN `product_uom_qty` (demand).

        Demand kedua move Final SELALU tetap sesuai `sale.order.line` asli
        (mis. 2000/100) sejak dibuat saat konfirmasi SO, dan method ini
        TIDAK PERNAH menyentuhnya -- itu murni komitmen order, bukan
        cerminan progres LOAD. Yang dihitung ulang kumulatif setiap LOAD
        selesai hanyalah `quantity`: berapa yang BENAR-BENAR sudah sampai,
        dipecah order/gratis lewat `rumus_gratis`. Menulis `move.quantity`
        langsung memicu inverse core `_set_quantity()` ->
        `_set_quantity_done()`, yang membuat/menyesuaikan `move_line_ids`
        dari quant yang tersedia di lokasi asal move (persis seperti core
        sendiri melakukan reservasi/`qty_done`) -- jadi TIDAK perlu
        `_action_assign()` manual sesudahnya, dan state move (assigned/
        partially_available) otomatis mengikuti dari situ.

        Hanya berlaku kalau pasangannya persis dua move dengan
        `order_selection` berbeda -- kalau tidak (mis. cuma ada move
        'order', tanpa gratis sama sekali), tidak ada yang perlu
        di-reallocate dan Final tetap satu move seperti biasa.

        Move gratis TIDAK PERNAH dibatalkan (`_action_cancel()`) di sini
        walau `qty_gratis` jadi 0 -- hanya `quantity`-nya yang dikosongkan.
        Alasannya: `stock.move._prepare_move_split_vals()` core membuang
        entri `move_dest_ids` yang state-nya `done`/`cancel` saat LOAD
        di-backorder (lihat `odoo/addons/stock/models/stock_move.py`
        `_prepare_move_split_vals`). Kalau move gratis dibatalkan pada
        LOAD leg PERTAMA (mis. karena baru sedikit yang datang, atau
        `rumus_gratis` belum terisi), setiap leg LOAD berikutnya (hasil
        backorder split) kehilangan move gratis dari `move_dest_ids`-nya --
        pasangannya jadi tinggal satu move ('order' saja), dan
        `_reallocate_gratis_final_pair` di atas selalu no-op sesudahnya.
        Akibatnya kumulatif Final BEKU di angka LOAD leg pertama, tidak
        pernah ikut bertambah walau LOAD berikutnya selesai -- persis
        laporan pada SO S00865 (macet di 1280 walau LOAD susulan 600 dan
        220 sudah/sedang selesai). Membiarkan move gratis tetap hidup
        (state apa pun selain done/cancel) menjaganya tetap ikut terbawa
        di `move_dest_ids` setiap split, sehingga pasangannya selalu
        lengkap dan kumulatifnya tidak pernah macet.
        """
        if len(finals_group) != 2:
            return
        if set(finals_group.mapped('order_selection')) != {'order', 'gratis'}:
            return

        order_move = finals_group.filtered(lambda m: m.order_selection == 'order')
        gratis_move = finals_group.filtered(lambda m: m.order_selection == 'gratis')

        qty_actual = sum(
            m.quantity for m in finals_group.move_orig_ids if m.state == 'done'
        )

        order_line = order_move.sale_line_id or order_move.purchase_line_id
        gratis_line = gratis_move.sale_line_id or gratis_move.purchase_line_id
        rumus_gratis = order_line.rumus_gratis if order_line else 0
        if gratis_line and gratis_line.rumus_gratis and gratis_line.rumus_gratis != rumus_gratis:
            _logger.warning(
                "[GRATIS-SPLIT] rumus_gratis order (%s) berbeda dengan gratis (%s) "
                "pada final move order=%s gratis=%s, dipakai nilai punya order",
                rumus_gratis, gratis_line.rumus_gratis, order_move.id, gratis_move.id,
            )

        # `rumus_gratis` dimasukkan manusia dalam SATUAN sale/purchase order
        # line (mis. "BAG 20", 1 bag = 20 kg) -- "21" berarti "1 gratis tiap
        # 21 BAG", bukan tiap 21 KG. Tapi `qty_actual` di atas datang dari
        # `move.quantity`, yang selalu dalam UoM STOK produk (kg). Membagi
        # keduanya langsung tanpa konversi menghasilkan angka pecahan yang
        # salah unit (mis. 1920 kg / 21 = 91.43 -> "91 gratis", padahal yang
        # benar 1920 kg = 96 BAG, 96 / 21 = 4.57 -> 4 gratis) -- floor()-nya
        # sendiri sudah benar, unit yang dibaginya yang keliru. Konversi dulu
        # ke UoM order line, floor di sana, baru konversi hasilnya balik ke
        # UoM move untuk ditulis ke `quantity`.
        order_uom = order_line.product_uom_id if order_line else order_move.product_uom
        move_uom = order_move.product_uom
        qty_actual_line_uom = move_uom._compute_quantity(qty_actual, order_uom) if order_uom != move_uom else qty_actual

        qty_gratis_line_uom = math.floor(qty_actual_line_uom / rumus_gratis) if rumus_gratis else 0
        qty_order_line_uom = qty_actual_line_uom - qty_gratis_line_uom

        if order_uom != move_uom:
            qty_gratis = order_uom._compute_quantity(qty_gratis_line_uom, move_uom)
            qty_order = order_uom._compute_quantity(qty_order_line_uom, move_uom)
        else:
            qty_gratis = qty_gratis_line_uom
            qty_order = qty_order_line_uom

        rounding = order_move.product_id.uom_id.rounding or 0.01
        targets = ((order_move, qty_order), (gratis_move, qty_gratis))
        for move, target in targets:
            if (
                move.state not in ('done', 'cancel')
                and float_compare(move.quantity, target, precision_rounding=rounding) != 0
            ):
                move.quantity = target

        self._repair_reallocated_lotless_reservations(order_move | gratis_move)

    def _repair_reallocated_lotless_reservations(self, moves):
        """Pindahkan reservasi fallback core ke quant lot yang tersedia."""
        lotless_lines = moves.move_line_ids.filtered(
            lambda line: line.state not in ('done', 'cancel')
            and line.quantity > 0
            and line.product_id.tracking != 'none'
            and not line.lot_id
            and not line.location_id.should_bypass_reservation()
        )
        for move in lotless_lines.move_id:
            lines = lotless_lines.filtered(lambda line, move=move: line.move_id == move)
            quantity = sum(lines.mapped('quantity_product_uom'))
            lotted_quants = self.env['stock.quant'].search([
                ('product_id', '=', move.product_id.id),
                ('location_id', 'child_of', move.location_id.id),
                ('lot_id', '!=', False),
            ])
            available = sum(
                max(quant.available_quantity, 0.0) for quant in lotted_quants
            )
            if float_compare(available, quantity, precision_rounding=move.product_id.uom_id.rounding) < 0:
                continue

            lines.unlink()
            move._update_reserved_quantity(quantity, move.location_id, strict=False)

    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        self.ensure_one()
        res = super()._prepare_move_line_vals(quantity=quantity, reserved_quant=reserved_quant)
        
        is_production_only = self._is_gr_prod()
        
        if is_production_only:
            res['stock_type'] = 'QI'
        elif reserved_quant and reserved_quant.stock_type:
            res['stock_type'] = reserved_quant.stock_type

        # `production_line_id` dan `pallet_ke` menempel pada barang, jadi quant
        # yang direservasi adalah sumber kebenarannya. Dulu keduanya HANYA
        # diisi dari move line asal di blok `move_orig_ids` di bawah, sehingga
        # setiap transfer tanpa move asal -- Bin to Bin, Split QTY Pallet, PICK
        # langsung dari stok -- selalu kehilangan keduanya, dan hilangnya ikut
        # menular ke quant tujuan lewat `_synchronize_quant()`.
        if reserved_quant:
            if reserved_quant.production_line_id:
                res['production_line_id'] = reserved_quant.production_line_id.id
            if reserved_quant.pallet_ke:
                res['pallet_ke'] = reserved_quant.pallet_ke

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
                'first_count': matched_line.first_count,
                'last_count': matched_line.last_count,
                'detail_text': matched_line.detail_text,
                'qty_packaging_sap': matched_line.qty_packaging_sap,
                'wh_category_id': matched_line.wh_category_id.id if matched_line.wh_category_id else False,
            }

            # `matched_line` bisa berasal dari fallback `origin_lines[:1]` yang
            # sama sekali tidak dicocokkan dengan pallet ini, jadi untuk field
            # turunan quant ia hanya boleh MENGISI KEKOSONGAN -- jangan sampai
            # menimpa nilai yang sudah benar dari `reserved_quant` dengan milik
            # pallet lain.
            if not res.get('production_line_id') and matched_line.production_line_id:
                update_vals['production_line_id'] = matched_line.production_line_id.id
            if not res.get('pallet_ke') and matched_line.pallet_ke:
                update_vals['pallet_ke'] = matched_line.pallet_ke
            if not is_production_only and not res.get('stock_type') and matched_line.stock_type:
                update_vals['stock_type'] = matched_line.stock_type

            res.update(update_vals)

        return res
