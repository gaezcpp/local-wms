from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging
import traceback
_logger = logging.getLogger(__name__)

class InheritStockMove(models.Model):
    _inherit = 'stock.move'

    uom_bag_id = fields.Many2one('uom.uom',  related='product_id.uom_bag_id', store=True)
    uom_pallet_id = fields.Many2one('uom.uom', related='product_id.uom_pallet_id', store=True)
    bag_qty = fields.Float(string="Quantity", compute="_compute_bag_qty", store=True)
    pallet_qty = fields.Float(string="Pallet Qty", compute="_compute_pallet_qty", store=True)
    product_packaging_id = fields.Many2one(comodel_name='product.packaging.sap', string="Product Packaging")
    qty_packaging_sap = fields.Float(string="Qty Packaging", compute='_compute_qty_packaging_sap')
    
    # @api.model_create_multi
    # def create(self, vals_list):
    #     moves = super().create(vals_list)
    #     moves.create_packaging_line()
    #     return moves

    # def write(self, vals):
    #     res = super().write(vals)
    #     return res

    # FIXING CREATE NEW PICKING
    def _is_checker_out_step(self):
        """Langkah Checker Out (CO), bukan Loading (LOAD).

        Keduanya sama-sama ber-``checker_out``; yang membedakan hanya
        ``split_package`` yang cuma aktif di Loading.
        """
        self.ensure_one()
        picking_type = self.picking_type_id
        return picking_type.checker_out and not picking_type.split_package

    def _find_available_loading_picking(self, sale_order):
        """Dokumen Loading milik Sale Order yang sama dan masih terbuka.

        Dicocokkan secara struktural, bukan lewat id yang di-hardcode: dokumen
        Loading berangkat dari lokasi tujuan Checker Out ini dan operation
        type-nya ber-``checker_out`` + ``split_package``.
        """
        self.ensure_one()
        return self.env['stock.picking'].sudo().search([
            ('sale_id', '=', sale_order.id),
            ('company_id', '=', self.company_id.id),
            ('location_id', '=', self.location_dest_id.id),
            ('picking_type_id.checker_out', '=', True),
            ('picking_type_id.split_package', '=', True),
            ('state', 'not in', ('done', 'cancel')),
        ], order='id', limit=1)

    def _find_loading_move(self, loading):
        """Baris Loading yang seharusnya disuplai oleh move Checker Out ini.

        Dokumen Loading sudah punya baris demand dari Sale Order, jadi hasil
        Checker Out cukup dijadikan sumber baris itu — bukan bikin baris baru.
        Pencocokannya per produk, lalu dipersempit dengan ``sale_line_id``
        (paling akurat) dan ``order_seq`` sebagai cadangan.
        """
        self.ensure_one()
        candidates = loading.move_ids.filtered(
            lambda m: m.product_id == self.product_id and m.state not in ('done', 'cancel')
        )
        if not candidates:
            return self.browse()

        by_sale_line = candidates.filtered(lambda m: m.sale_line_id == self.sale_line_id)
        if by_sale_line:
            return by_sale_line[:1]

        by_order_seq = candidates.filtered(
            lambda m: m.order_seq and m.order_seq == self.order_seq
        )
        if by_order_seq:
            return by_order_seq[:1]

        return candidates[:1]

    def _get_loading_rule(self, loading):
        """Rule Loading milik channel Sale Order ini.

        Diambil dari move dokumen Loading yang sudah ada supaya rule-nya persis
        rule channel yang dipakai SO tersebut (Franco / Loco / STO). Kalau
        dokumen Loading dibuat manual dan move-nya tanpa ``rule_id``, jatuh ke
        pencarian rule berdasarkan lokasi + operation type.
        """
        self.ensure_one()
        rule = loading.move_ids.filtered(lambda m: m.rule_id)[:1].rule_id
        if rule:
            return rule

        return self.env['stock.rule'].sudo().search([
            ('location_src_id', '=', self.location_dest_id.id),
            ('location_dest_id', '=', loading.location_dest_id.id),
            ('picking_type_id', '=', loading.picking_type_id.id),
            ('company_id', '=', self.company_id.id),
        ], limit=1)

    def _push_checker_out_to_loading(self):
        """Sambungkan move Checker Out yang buntu ke dokumen Loading milik SO-nya.

        Picking hasil wizard ``create.new.picking`` dibuat manual, bukan lewat
        procurement, sehingga rule Loading (yang ber-``action='pull'``) tidak
        pernah jalan untuk move tersebut. Move Checker Out-nya berhenti di
        ``FINI/STG - OUT Checker Out`` tanpa next transfer.

        Dokumen Loading milik SO tersebut sudah punya baris demand-nya sendiri,
        jadi move Checker Out cukup di-link sebagai sumber baris itu lewat
        ``move_dest_ids``. Tidak ada ``stock.move`` maupun ``stock.move.line``
        baru yang dibuat: demand di Loading tidak berubah, dan core yang
        mereservasi barangnya (``_action_done`` memanggil
        ``moves_todo.move_dest_ids._action_assign()`` tepat setelah
        ``_push_apply``).

        ``stock.move`` baru hanya dibuat sebagai cadangan, kalau produknya sama
        sekali belum ada di dokumen Loading — dan itu pun dirakit oleh rule
        lewat ``_run_push``, bukan tangan.

        Chain SO normal tidak mungkin tersentuh: move Checker Out di chain itu
        sudah punya ``move_dest_ids``, sehingga sudah disaring core lewat
        ``_skip_push()`` sebelum ``_push_apply()`` dipanggil.
        """
        pushed = self.browse()

        for move in self:
            if move.move_dest_ids or not move._is_checker_out_step():
                continue

            sale_order = move.sale_line_id.order_id
            if not sale_order:
                continue

            loading = move._find_available_loading_picking(sale_order)
            if not loading:
                _logger.info(
                    "[CO->LOAD] move %s: tidak ada dokumen Loading terbuka untuk SO %s",
                    move.id, sale_order.name
                )
                continue

            load_move = move._find_loading_move(loading)
            if load_move:
                move.write({'move_dest_ids': [(4, load_move.id)]})
                loading.message_post(
                    body=f"Baris {load_move.product_id.display_name} disuplai dari "
                         f"Checker Out {move.picking_id.name}."
                )
                _logger.info(
                    "[CO->LOAD] %s -> %s baris move %s (SO %s)",
                    move.picking_id.name, loading.name, load_move.id, sale_order.name
                )
                continue

            # Produknya belum ada di dokumen Loading: biarkan rule channel yang
            # membuatkan barisnya, lalu tempelkan ke dokumen yang sama.
            rule = move._get_loading_rule(loading)
            if not rule:
                _logger.warning(
                    "[CO->LOAD] move %s: rule Loading tidak ditemukan untuk dokumen %s",
                    move.id, loading.name
                )
                continue

            new_move = rule.sudo()._run_push(move)
            if not new_move:
                continue

            if new_move.location_dest_id == loading.location_dest_id:
                new_move.write({'picking_id': loading.id})

            pushed |= new_move
            _logger.info(
                "[CO->LOAD] %s -> %s baris baru (SO %s)",
                move.picking_id.name, loading.name, sale_order.name
            )

        if pushed:
            pushed.sudo()._action_confirm()

        return pushed

    def _push_apply(self):
        new_moves = super()._push_apply()
        return new_moves | self._push_checker_out_to_loading()
    # FIXING CREATE NEW PICKING
    
    def _get_fields_stock_barcode(self):
        res = super()._get_fields_stock_barcode()
        return res + [
            'bag_qty',
            'pallet_qty',
            'uom_bag_id',
            'uom_pallet_id',
            'qty_packaging_sap',
        ]
        
    @api.depends('quantity', 'uom_bag_id', 'uom_pallet_id')
    def _compute_bag_qty(self):
        for line in self:
            if not line.uom_bag_id or not line.quantity:
                line.bag_qty = 0.0
                continue

            line.bag_qty = ((line.quantity * line.product_uom.factor) / 1000) / (line.uom_bag_id.factor / 1000)

    @api.depends('quantity', 'uom_pallet_id')
    def _compute_pallet_qty(self):
        for line in self:
            if not line.quantity or not line.uom_pallet_id:
                line.pallet_qty = 0.0
                continue

            line.pallet_qty = ((line.quantity * line.product_uom.factor) / 1000) / (line.uom_pallet_id.factor / 1000)
            
    @api.depends('move_line_ids.qty_packaging_sap')
    def _compute_qty_packaging_sap(self):
        for move in self:
            move.qty_packaging_sap = sum(move.move_line_ids.mapped('qty_packaging_sap'))
            
    def create_packaging_line(self):
        Packaging = self.env['product.packaging.sap']
        PickingPackaging = self.env['picking.packaging.line']
        pickings = self.mapped('picking_id').filtered(lambda p: p)
        if not pickings:
            return

        all_templates = self.mapped('product_id.product_tmpl_id')
        companies = pickings.mapped('company_id')

        packaging_data = Packaging.search([
            ('product_id', 'in', all_templates.ids),
            ('company_id', 'in', companies.ids)
        ])

        packaging_map = {
            (p.product_id.id, p.company_id.id): p
            for p in packaging_data
        }

        for picking in pickings:
            moves = picking.move_ids.filtered(lambda m: m.product_id)
            if not moves:
                continue

            existing_products = set(picking.product_packaging_ids.mapped('product_id').ids)
            origin_sloc_map = {}

            origin_moves = moves.filtered(lambda m: m.origin_returned_move_id)
            origin_pickings = origin_moves.mapped(
                'origin_returned_move_id.picking_id'
            )

            if origin_pickings:
                origin_lines = origin_pickings.mapped('product_packaging_ids')
                origin_sloc_map = {
                    line.product_id.id: line.sloc_id.id
                    for line in origin_lines if line.sloc_id
                }

            create_vals = []
            for move in moves:
                tmpl_id = move.product_id.product_tmpl_id.id

                if tmpl_id in existing_products:
                    continue

                packaging = packaging_map.get((tmpl_id, picking.company_id.id))
                if not packaging:
                    continue
                
                packaging_type = picking.picking_type_id.packaging_type_id
                create_vals.append({
                    'picking_id': picking.id,
                    'product_id': tmpl_id,
                    'product_uom_desc': packaging.product_uom_desc,
                    'packaging_code': packaging.packaging_code,
                    'packaging_desc': packaging.packaging_desc,
                    'company_id': picking.company_id.id,
                    'packaging_type_id': packaging_type.id,
                    'move_type_sap': packaging_type.move_type_sap,
                    'sloc_id': origin_sloc_map.get(tmpl_id, False),
                })

            if create_vals:
                PickingPackaging.create(create_vals)