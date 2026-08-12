from collections import defaultdict

from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class InheritBaseStockMoveLine(models.Model):
    _inherit = 'stock.move.line'
    
    production_line_id = fields.Many2one(comodel_name='production.line', string="Line")
    first_count = fields.Float(string="First Count")
    last_count = fields.Float(string="Last Count")
    detail_text = fields.Char(string="Detail Text")
    production_only = fields.Boolean(string="Production Only", related='picking_type_id.production_only', store=True)
    sloc_name = fields.Char(related='location_dest_id.sloc_name', string="SLOC Name", store=True)
    sloc_id = fields.Many2one(comodel_name='storage.location', string="SLOC")
    production_shift_id = fields.Many2one(related='picking_id.production_shift_id', string="Shift", store=True)
    production_order_name = fields.Char(related='picking_id.production_order_name', string="Production Order Name", store=True)
    stock_type = fields.Selection([
        ('QI', 'QI'),
        ('BLOCKED', 'BLOCKED'),
        ('UU', 'UU'),
    ], string="Stock Type", default='QI', index=True)
    
    # ini dipake kalo odoo.sh salah
    def _skip_custom_logic(self):
        ctx = self.env.context
        return (
            ctx.get('inventory_mode') or
            ctx.get('install_mode') or
            ctx.get('install_demo') or
            ctx.get('test_enable')
        )
    
    def _get_or_create_lot(self):
        self.ensure_one()
        if not self.move_id.product_id:
            return False
        
        if not self.production_line_id:
            return False

        prod_code_rec = self.env['production.code'].sudo().search([('company_id', '=', self.company_id.id)], limit=1)
        if not prod_code_rec or not prod_code_rec.code:
            raise ValidationError("Konfigurasi Production Code (Format Lot) belum diatur untuk company ini!")

        prod_group = self.env['production.group'].sudo().search([
            ('user_id', '=', self.env.user.id),
            ('company_id', '=', self.company_id.id)
        ], limit=1)
        
        group_code = prod_group.code if prod_group else ''
        localdict = {
            'self': self,
            'picking': self.picking_id,
            'moveline': self,
            'fields': fields,
            'str': str,
            'int': int,
            'group_code': group_code,
        }

        try:
            lot_name = eval(f'f"""{prod_code_rec.code}"""', localdict)
        except Exception as e:
            raise ValidationError(f"Terjadi kesalahan saat memproses format Production Code: {e}")

        lot = self.env['stock.lot'].sudo().search([
            ('name', '=', lot_name),
            ('product_id', '=', self.move_id.product_id.id),
            ('company_id', '=', self.company_id.id)
        ], limit=1)

        if not lot:
            lot = self.env['stock.lot'].sudo().search([
                ('id', '=', self.lot_id.id),
                ('product_id', '=', self.move_id.product_id.id),
                ('company_id', '=', self.company_id.id)
            ], limit=1)
            if not lot:
                lot = self.env['stock.lot'].create({
                    'name': lot_name,
                    'product_id': self.move_id.product_id.id,
                    'company_id': self.company_id.id,
                    'po_sap_id': self.picking_id.po_sap_id.id if self.picking_id.po_sap_id else False,
                    'production_line_id': self.production_line_id.id if self.production_line_id else False,
                })

        return lot

    @api.model_create_multi
    def create(self, vals_list):
        lookup_indexes = [
            i for i, vals in enumerate(vals_list)
            if not vals.get('stock_type') and vals.get('location_id') and vals.get('product_id')
        ]

        if lookup_indexes:
            location_ids = {vals_list[i]['location_id'] for i in lookup_indexes}
            product_ids = {vals_list[i]['product_id'] for i in lookup_indexes}
            candidate_quants = self.env['stock.quant'].sudo().search([
                ('location_id', 'in', list(location_ids)),
                ('product_id', 'in', list(product_ids)),
            ])

            for i in lookup_indexes:
                vals = vals_list[i]
                matching_quants = candidate_quants.filtered(
                    lambda q, vals=vals: q.location_id.id == vals['location_id']
                    and q.product_id.id == vals['product_id']
                    and (not vals.get('lot_id') or q.lot_id.id == vals['lot_id'])
                    and (not vals.get('package_id') or q.package_id.id == vals['package_id']),
                )
                if matching_quants:
                    source_quant = matching_quants[0]
                    if source_quant.stock_type:
                        vals['stock_type'] = source_quant.stock_type

        records = super().create(vals_list)

        for rec in records:
            if rec._is_gr_prod():
                lot = rec._get_or_create_lot()
                if lot:
                    rec.with_context(skip_lot_aft=True).write({'lot_id': lot.id})
        return records

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get('skip_lot_aft'):
            return res

        gr_prod_recs = self.filtered(lambda r: r._is_gr_prod())
        stock_type_recs = gr_prod_recs.filtered(lambda r: r.stock_type and r.state == 'done')

        if stock_type_recs:
            candidate_quants = self.env['stock.quant'].sudo().search([
                ('product_id', 'in', stock_type_recs.product_id.ids),
                ('location_id', 'in', stock_type_recs.location_dest_id.ids),
            ])

            groups = defaultdict(lambda: self.env['stock.move.line'])
            for rec in stock_type_recs:
                package_key = (rec.result_package_id.id or rec.package_id.id) or False
                lot_key = rec.lot_id.id if rec.lot_id else False
                key = (rec.product_id.id, rec.location_dest_id.id, package_key, lot_key, rec.stock_type)
                groups[key] |= rec

            for (product_id, location_dest_id, package_key, lot_key, stock_type), recs in groups.items():
                matching_quants = candidate_quants.filtered(
                    lambda q, product_id=product_id, location_dest_id=location_dest_id,
                    package_key=package_key, lot_key=lot_key: q.product_id.id == product_id
                    and q.location_id.id == location_dest_id
                    and q.package_id.id == package_key
                    and (not lot_key or q.lot_id.id == lot_key),
                )
                if matching_quants:
                    matching_quants.write({'stock_type': stock_type})

        for rec in gr_prod_recs:
            trigger_fields = {'production_line_id', 'expiration_date'}
            if trigger_fields & set(vals.keys()):
                if rec.production_line_id and rec.expiration_date:
                    lot = rec._get_or_create_lot()
                    if lot:
                        rec.with_context(skip_lot_aft=True).write({'lot_id': lot.id})
        return res
    
    def _is_gr_prod(self, vals=None):
        picking = False
        prod_in_move_type = self.env['ir.config_parameter'].sudo().get_param('prod_in_move_type')
        if not prod_in_move_type:
            raise ValidationError("prod_in_move_type pada Operation Type belum disetting!")
        else:
            if vals and vals.get('picking_id'):
                picking = self.env['stock.picking'].sudo().browse(vals['picking_id'])
            elif self.picking_id:
                picking = self.picking_id
            elif self.move_id and self.move_id.picking_id:
                picking = self.move_id.picking_id
            return picking and picking.picking_type_id.move_type_sap == str(prod_in_move_type)
    
    def _get_linkable_moves(self):
        """Jangan pernah melekatkan move line ke move 'gratis' yang masih terkunci.

        Core hanya menyaring kandidat berdasarkan `product_id`
        (`stock/models/stock_move_line.py::_get_linkable_moves`), tanpa melihat
        `order_selection`. Move line baru dari Barcode dikirim tanpa `move_id`
        (`_createCommandVals()` tidak menyertakannya), sehingga pemilihan move
        diserahkan ke method ini — dan kunci sortir core `m.quantity < m.product_qty`
        bisa menaikkan move gratis ke urutan pertama begitu move 'order'
        pasangannya terbaca sudah penuh. Akibatnya qty masuk ke move gratis
        padahal `gratis_locked` masih True.

        `_action_assign()` sudah mengecualikan move gratis terkunci, tapi jalur
        create ini tidak lewat sana, jadi pengamannya dipasang di sini.
        """
        moves = super()._get_linkable_moves()
        if not moves:
            return moves

        unlocked = [
            move for move in moves
            if move.order_selection != 'gratis' or not move._is_gratis_locked()
        ]
        if not unlocked:
            # Satu-satunya kandidat memang move gratis terkunci. Perilaku core
            # dipertahankan supaya tidak malah terbentuk move baru di luar SAP.
            _logger.warning(
                "[GRATIS-LOCK] move line %s: semua kandidat move terkunci, tetap "
                "memakai move %s", self.id or '(baru)', moves[0].id,
            )
            return moves

        if len(unlocked) != len(moves):
            _logger.info(
                "[GRATIS-LOCK] move line %s: melewati move gratis terkunci %s, "
                "dipakai move %s",
                self.id or '(baru)',
                [move.id for move in moves if move not in unlocked],
                unlocked[0].id,
            )
        return unlocked

    def _free_reservation(self, product_id, location_id, quantity, lot_id=None, package_id=None, owner_id=None, ml_ids_to_ignore=None):
        # Core stock_move_line._action_done() calls _free_reservation() with
        # context key 'quants_cache' explicitly set to None (not removed) when
        # available_qty goes negative. stock.quant.create()'s _add_to_cache()
        # closure only checks that the 'quants_cache' key is present in the
        # context, not that its value is truthy, so it ends up doing
        # `None[...]` and raises TypeError: 'NoneType' object is not
        # subscriptable. Rebuild a fresh, empty cache of the same shape core
        # uses elsewhere so the lookup succeeds; the cache is scoped to this
        # call only, so no business behavior changes.
        records = self
        if 'quants_cache' in self.env.context and self.env.context.get('quants_cache') is None:
            records = self.with_context(quants_cache=defaultdict(lambda: self.env['stock.quant']))
        return super(InheritBaseStockMoveLine, records)._free_reservation(
            product_id, location_id, quantity, lot_id=lot_id, package_id=package_id,
            owner_id=owner_id, ml_ids_to_ignore=ml_ids_to_ignore,
        )

    # untuk stock.lot.aft ngurangin yang UU
    def _action_done(self):
        for line in self:
            picking_type = line.picking_id.picking_type_code
            if picking_type == 'outgoing' and line.lot_id:
                lot = line.lot_id

                qty_to_reduce = line.qty_done
                bag_to_reduce = line.bag_qty

                if not bag_to_reduce:
                    product_uom = line.product_id.uom_id
                    uom_bag = line.product_id.uom_bag_id
                    if product_uom and uom_bag:
                        bag_to_reduce = product_uom._compute_quantity(qty_to_reduce, uom_bag)

                aft_uu_lines = lot.lot_aft_ids.filtered(
                    lambda a: a.stock_type == 'UU' and (a.quantity > 0 or a.bag_qty > 0)
                )

                remaining_qty = qty_to_reduce
                remaining_bag = bag_to_reduce

                for aft in aft_uu_lines:
                    if remaining_qty <= 0 and remaining_bag <= 0:
                        break

                    deduct_qty = 0
                    deduct_bag = 0

                    if remaining_qty > 0:
                        deduct_qty = min(aft.quantity, remaining_qty)
                        aft.quantity -= deduct_qty
                        remaining_qty -= deduct_qty

                    if remaining_bag > 0:
                        deduct_bag = min(aft.bag_qty, remaining_bag)
                        aft.bag_qty -= deduct_bag
                        remaining_bag -= deduct_bag

                    lot.message_post(
                        body=(
                            f"Updated from {line.picking_id.name}: "
                            f"Quantity -{deduct_qty} {aft.uom_id.name or ''} → Remaining {aft.quantity} {aft.uom_id.name or ''} | "
                            f"Bag Qty -{deduct_bag} {aft.uom_bag_id.name or ''} → Remaining {aft.bag_qty} {aft.uom_bag_id.name or ''}"
                        )
                    )
                    
        res = super()._action_done()
        return res