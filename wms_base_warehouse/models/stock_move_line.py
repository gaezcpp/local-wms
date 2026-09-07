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
    # Sengaja TANPA `default='QI'`. Client Barcode tidak pernah mengirim
    # `stock_type` (baik `_getFieldToWrite()` maupun `_createCommandVals()`
    # core tidak memuatnya), jadi default itu dulu menjadi nilai final setiap
    # kali pencarian quant asal di `create()` meleset -- diam-diam mengubah
    # stok UU menjadi QI pada Bin to Bin (INT) dan Split QTY Pallet (P2P).
    # QI untuk GR produksi sekarang dipasang eksplisit di
    # `_apply_gr_prod_stock_type()` dan `stock.move._prepare_move_line_vals()`.
    stock_type = fields.Selection([
        ('QI', 'QI'),
        ('BLOCKED', 'BLOCKED'),
        ('UU', 'UU'),
    ], string="Stock Type", index=True)
    
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
            # Dulu di sini ada fallback `search([('id','=',self.lot_id.id)])`:
            # kalau lot dengan nama hasil format belum ada, method ini
            # mengembalikan lot yang KEBETULAN sudah menempel di baris. Efeknya
            # nama lot tidak pernah bisa dikoreksi. Itu yang membuat GR PO
            # 160110003473 line 71 tetap memakai lot `3965732 - 18022028`
            # (punya line 94) walau `production_line_id` sudah ditulis ulang ke
            # line 71 oleh `production.order.sap.action_picking_po_sap()`:
            # nama yang benar (`3765732 - ...`) belum ada, jadi fallback itu
            # mengunci lot lama. Kontrak method ini adalah "lot dengan nama
            # hasil format" -- kalau belum ada, ya dibuat.
            lot = self.env['stock.lot'].create({
                'name': lot_name,
                'product_id': self.move_id.product_id.id,
                'company_id': self.company_id.id,
                'po_sap_id': self.picking_id.po_sap_id.id if self.picking_id.po_sap_id else False,
                'production_line_id': self.production_line_id.id if self.production_line_id else False,
            })

        return lot

    # Atribut yang menempel pada BARANG, bukan pada dokumen. Kalau pemanggil
    # tidak mengirimnya, nilainya diwarisi dari quant di lokasi asal -- itulah
    # satu-satunya sumber kebenaran yang tersedia untuk baris hasil scan,
    # karena client Barcode tidak pernah mengirim ketiganya.
    _QUANT_INHERITED_FIELDS = ('stock_type', 'production_line_id', 'pallet_ke')

    def _fill_quant_inherited_fields(self, vals_list):
        """Isi field turunan quant pada baris baru sebelum disimpan.

        Urutannya: warisi dari quant asal dulu, baru fallback GR produksi
        untuk `stock_type`. Kalau keduanya tidak berlaku, field sengaja
        dibiarkan kosong -- lebih jujur daripada mengarang 'QI' seperti
        default field yang lama.
        """
        pending = [
            vals for vals in vals_list
            if not all(vals.get(name) for name in self._QUANT_INHERITED_FIELDS)
        ]
        if not pending:
            return

        self._fill_from_source_quant(pending)

        still_empty = [vals for vals in pending if not vals.get('stock_type')]
        if still_empty:
            self._apply_gr_prod_stock_type(still_empty)

    def _fill_from_source_quant(self, vals_list):
        """Warisi `_QUANT_INHERITED_FIELDS` dari quant di lokasi asal.

        Pencocokan `package_id` harus SIMETRIS: baris tanpa package hanya boleh
        mewarisi dari quant tanpa package. Versi lama memakai
        `not vals.get('package_id') or ...`, sehingga saat barang belum
        dipallet syarat package tidak dipasang sama sekali dan quant milik
        pallet lain di bin yang sama ikut jadi kandidat -- lalu diambil
        `matching_quants[0]` (id terkecil). Itulah asal "UU tiba-tiba jadi QI"
        pada INT/P2P.

        `lot_id` tetap asimetris: baris tanpa lot memang sah mewakili beberapa
        lot sekaligus, jadi kandidatnya tidak boleh dipersempit ke lot kosong.

        Lokasi asal juga harus lokasi stok NYATA (`internal`/`transit`). Di
        lokasi virtual -- `Production`, `Inventory adjustment`, supplier,
        customer -- quant hanya berisi jurnal lawan dari transaksi lampau
        (semuanya negatif dan menumpuk selamanya), bukan barang yang sedang
        diambil. Mewarisi apa pun dari sana bukan cuma tidak bermakna, tapi
        aktif merusak: baris GR produksi yang dibuat `action_confirm()` mewarisi
        `production_line_id` dari salah satu ratusan quant lawan di lokasi
        `Production`, dan `create()` langsung memakai nilai itu untuk menamai
        lot lewat `_get_or_create_lot()` -- sebelum
        `production.order.sap.action_picking_po_sap()` sempat menulis production
        line yang sebenarnya.
        """
        indexes = [
            i for i, vals in enumerate(vals_list)
            if vals.get('location_id') and vals.get('product_id')
        ]
        if not indexes:
            return

        location_ids = {vals_list[i]['location_id'] for i in indexes}
        product_ids = {vals_list[i]['product_id'] for i in indexes}
        candidate_quants = self.env['stock.quant'].sudo().search([
            ('location_id', 'in', list(location_ids)),
            ('location_id.usage', 'in', ('internal', 'transit')),
            ('product_id', 'in', list(product_ids)),
        ])
        if not candidate_quants:
            return

        for i in indexes:
            vals = vals_list[i]
            package_id = vals.get('package_id') or False
            lot_id = vals.get('lot_id') or False
            matching = candidate_quants.filtered(
                lambda q, vals=vals, package_id=package_id, lot_id=lot_id:
                q.location_id.id == vals['location_id']
                and q.product_id.id == vals['product_id']
                and (q.package_id.id or False) == package_id
                and (not lot_id or q.lot_id.id == lot_id),
            )
            if not matching:
                continue

            for name in self._QUANT_INHERITED_FIELDS:
                if vals.get(name):
                    continue
                source = self._resolve_source_quant(matching, name, vals)
                if not source:
                    continue
                value = source[name]
                vals[name] = value.id if self._fields[name].type == 'many2one' else value

    def _resolve_source_quant(self, quants, field_name, vals):
        """Pilih satu quant rujukan untuk `field_name`.

        Satu bin bisa memuat satu produk dengan atribut berbeda-beda sekaligus
        (mis. sisa UU berdampingan dengan lot BLOCKED, atau dua pallet dari
        production line berbeda). Kalau begitu, quant yang benar-benar ada
        isinya yang menang; kalau masih ambigu juga, pilih yang qty-nya
        terbesar dan catat peringatannya supaya kasusnya bisa ditelusuri,
        bukan hilang tanpa jejak seperti sebelumnya.
        """
        candidates = quants.filtered(lambda q, name=field_name: q[name])
        if not candidates:
            return self.env['stock.quant']

        values = {q[field_name] for q in candidates}
        if len(values) == 1:
            return candidates[0]

        with_qty = candidates.filtered(lambda q: q.quantity > 0)
        if len({q[field_name] for q in with_qty}) == 1:
            return with_qty[0]

        pool = with_qty or candidates
        winner = pool.sorted(key=lambda q: q.quantity, reverse=True)[0]
        _logger.warning(
            "[QUANT-INHERIT] lokasi %s produk %s lot %s package %s: kandidat "
            "quant punya %s campuran %s, dipakai %r (qty %s dari quant %s)",
            vals.get('location_id'), vals.get('product_id'), vals.get('lot_id'),
            vals.get('package_id'), field_name, sorted(map(str, values)),
            winner[field_name], winner.quantity, winner.id,
        )
        return winner

    # Field yang menentukan quant mana yang jadi sumber kebenaran. Client
    # Barcode tidak pernah mengirim satu baris sekali jadi: baris dibuat lebih
    # dulu (kerap tanpa lot / tanpa package, karena operator baru men-scan
    # produknya), lalu detailnya menyusul lewat `write()` pada save berikutnya.
    # Selama `stock_type` hanya ditentukan sekali di `create()`, nilainya
    # terkunci pada tebakan awal itu -- dan tebakan dari bin campur bisa jatuh
    # ke pallet QI walau yang di-scan UU.
    _QUANT_MATCH_FIELDS = ('location_id', 'product_id', 'lot_id', 'package_id')

    def _quant_match_vals(self):
        self.ensure_one()
        return {
            'location_id': self.location_id.id,
            'product_id': self.product_id.id,
            'lot_id': self.lot_id.id,
            'package_id': self.package_id.id,
        }

    def _refresh_quant_inherited_fields(self):
        """Hitung ulang field turunan quant untuk baris yang SUDAH tersimpan.

        Dipakai dua kali:

        * dari `write()`, begitu salah satu `_QUANT_MATCH_FIELDS` berubah --
          quant sumbernya jadi berbeda, jadi `stock_type` hasil tebakan lama
          tidak berlaku lagi;
        * dari `_action_done()`, sebagai kesempatan terakhir mengisi baris yang
          waktu `create()` belum menemukan quant apa pun (mis. barangnya baru
          di-unpack ke bin itu setelah barisnya dibuat). Tanpa ini quant tujuan
          lahir dengan `stock_type` kosong.

        Aturannya:

        * `stock_type` mengikuti quant sumber -- itu atribut BARANG, jadi quant
          yang menang, bukan nilai yang sudah terlanjur menempel di baris;
        * kalau tidak ada quant yang cocok, nilai lama DIPERTAHANKAN (jangan
          sampai refresh malah mengosongkan yang sudah benar);
        * `production_line_id` dan `pallet_ke` hanya mengisi kekosongan, karena
          keduanya bisa ditulis sengaja dari luar (mis.
          `production.order.sap.action_picking_po_sap()`);
        * baris GR produksi dilewati -- `stock_type`-nya dipasang eksplisit QI
          oleh `_apply_gr_prod_stock_type()`, bukan diwarisi dari quant.
        """
        todo = self.filtered(
            lambda ml: ml.state not in ('done', 'cancel')
            and ml.location_id
            and ml.product_id
            and not ml._is_gr_prod()
        )
        if not todo:
            return

        vals_by_line = {line.id: line._quant_match_vals() for line in todo}
        self._fill_from_source_quant(list(vals_by_line.values()))

        for line in todo:
            vals = vals_by_line[line.id]
            update = {}
            new_stock_type = vals.get('stock_type')
            if new_stock_type and new_stock_type != line.stock_type:
                _logger.info(
                    "[QUANT-INHERIT] move line %s: stock_type %r -> %r mengikuti "
                    "quant sumber (lokasi %s, lot %s, package %s)",
                    line.id, line.stock_type, new_stock_type,
                    vals['location_id'], vals['lot_id'], vals['package_id'],
                )
                update['stock_type'] = new_stock_type
            for name in ('production_line_id', 'pallet_ke'):
                if not line[name] and vals.get(name):
                    update[name] = vals[name]
            if update:
                line.write(update)

    def _gr_prod_picking_ids(self, vals_list):
        """Resolusi picking GR produksi untuk sekumpulan vals.

        Mengembalikan `(gr_picking_ids, picking_by_move)` supaya pemanggil bisa
        memetakan tiap vals ke picking-nya tanpa query berulang: baris dari
        client Barcode sering dikirim dengan `move_id` saja, tanpa `picking_id`.
        """
        prod_in_move_type = self.env['ir.config_parameter'].sudo().get_param('prod_in_move_type')
        if not prod_in_move_type:
            return set(), {}

        picking_ids = {vals['picking_id'] for vals in vals_list if vals.get('picking_id')}
        move_ids = {
            vals['move_id'] for vals in vals_list
            if vals.get('move_id') and not vals.get('picking_id')
        }

        picking_by_move = {}
        if move_ids:
            for move in self.env['stock.move'].sudo().browse(move_ids).exists():
                picking_by_move[move.id] = move.picking_id.id
                if move.picking_id:
                    picking_ids.add(move.picking_id.id)

        if not picking_ids:
            return set(), picking_by_move

        gr_picking_ids = {
            picking.id
            for picking in self.env['stock.picking'].sudo().browse(picking_ids).exists()
            if picking.picking_type_id.move_type_sap == str(prod_in_move_type)
        }
        return gr_picking_ids, picking_by_move

    def _apply_gr_prod_stock_type(self, vals_list):
        """GR produksi selalu masuk sebagai QI.

        Dulu ini kebetulan tertangani oleh `default='QI'` pada field. Sekarang
        dipasang eksplisit supaya hanya GR yang kena, bukan semua baris yang
        pencarian quant-nya meleset.
        """
        gr_picking_ids, picking_by_move = self._gr_prod_picking_ids(vals_list)
        if not gr_picking_ids:
            return

        for vals in vals_list:
            picking_id = vals.get('picking_id') or picking_by_move.get(vals.get('move_id'))
            if picking_id in gr_picking_ids:
                vals['stock_type'] = 'QI'

    def _strip_gr_prod_lot_name(self, vals_list):
        """Nama lot GR produksi tidak boleh datang dari barcode yang di-scan.

        Picking GR produksi memakai `use_create_lots=True`, jadi core
        (`stock/models/stock_move_line.py::_action_done`) akan membuat
        `stock.lot` dari `lot_name` apa adanya begitu `lot_id` masih kosong.
        Di lapangan operator kerap men-scan QR PO SAP -- payload-nya
        `f"{po_number}|{production_line.code}"`, lihat
        `wms_production_order_sap/wizards/qr_po_sap.py::_get_qr_image_base64` --
        di layar Barcode. Karena barcode itu tidak cocok dengan produk/lokasi/
        pallet mana pun, core menganggapnya nomor lot baru
        (`stock_barcode/static/src/models/barcode_model.js`, blok "we assume
        it's a new lot/serial number") dan lahirlah lot bernama
        `160110003526|71`.

        Satu-satunya sumber nama lot GR produksi adalah `_get_or_create_lot()`,
        jadi `lot_name` dibuang di sini dan diisi ulang dari lot hasil generate.
        """
        pending = [vals for vals in vals_list if vals.get('lot_name')]
        if not pending:
            return

        gr_picking_ids, picking_by_move = self._gr_prod_picking_ids(pending)
        if not gr_picking_ids:
            return

        for vals in pending:
            picking_id = vals.get('picking_id') or picking_by_move.get(vals.get('move_id'))
            if picking_id in gr_picking_ids:
                _logger.warning(
                    "[GR-PROD-LOT] picking %s: lot_name %r diabaikan, nama lot "
                    "GR produksi dihasilkan dari Production Code",
                    picking_id, vals['lot_name'],
                )
                vals['lot_name'] = False

    @api.model_create_multi
    def create(self, vals_list):
        self._fill_quant_inherited_fields(vals_list)
        self._strip_gr_prod_lot_name(vals_list)

        records = super().create(vals_list)

        for rec in records:
            if rec._is_gr_prod():
                lot = rec._get_or_create_lot()
                if lot:
                    rec.with_context(skip_lot_aft=True).write({'lot_id': lot.id})
        return records

    # Field yang bisa mengubah hasil propagasi stock_type ke quant atau nama lot.
    # Penulisan lain (picked, date, reference, state antar-langkah, dsb.) tidak
    # perlu memicu ulang kedua blok di bawah.
    _GR_PROD_TRIGGER_FIELDS = frozenset({
        'state', 'stock_type', 'quantity', 'lot_id', 'package_id',
        'result_package_id', 'location_dest_id', 'product_id',
        'production_line_id', 'expiration_date',
        # Mengubah move/picking bisa mengubah hasil _is_gr_prod() itu sendiri.
        'move_id', 'picking_id',
    })

    def write(self, vals):
        if vals.get('lot_name'):
            # Sama seperti pada `create()`: pada GR produksi `lot_name` hanya
            # bisa berasal dari scan yang salah alamat (QR PO SAP), bukan dari
            # data yang sah. Recordset dipecah supaya baris non-GR -- Checker
            # IN, adjustment, dsb. -- tetap boleh memakai lot_name.
            gr_prod = self.filtered(lambda r: r._is_gr_prod())
            if gr_prod:
                _logger.warning(
                    "[GR-PROD-LOT] move line %s: lot_name %r diabaikan, nama lot "
                    "GR produksi dihasilkan dari Production Code",
                    gr_prod.ids, vals['lot_name'],
                )
                others = self - gr_prod
                if others:
                    others.write(vals)
                return gr_prod.write(dict(vals, lot_name=False))

        res = super().write(vals)

        # Kunci pencocokan quant berubah -> quant sumbernya juga berubah, jadi
        # `stock_type` hasil `create()` harus dihitung ulang. `stock_type` yang
        # ikut dikirim di vals ini dianggap keputusan pemanggil dan tidak
        # diganggu.
        if 'stock_type' not in vals and set(self._QUANT_MATCH_FIELDS) & set(vals):
            self._refresh_quant_inherited_fields()

        if self.env.context.get('skip_lot_aft'):
            return res
        if not self._GR_PROD_TRIGGER_FIELDS & set(vals):
            return res

        gr_prod_recs = self.filtered(lambda r: r._is_gr_prod())
        if not gr_prod_recs:
            return res

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

    def _ensure_gr_prod_lot(self):
        """Pastikan tiap baris GR produksi punya lot hasil `_get_or_create_lot()`.

        Dipanggil sebelum `super()._action_done()` supaya core tidak pernah
        sampai ke `_create_and_assign_production_lot()` untuk baris GR -- di
        sanalah dulu nama lot liar hasil scan terbentuk. Kalau lot memang tidak
        bisa dibuat, lebih baik validasi ditolak dengan pesan yang jelas
        daripada stok masuk dengan nama lot yang salah dan harus dibersihkan
        manual.
        """
        if not self.env['ir.config_parameter'].sudo().get_param('prod_in_move_type'):
            # Tanpa parameter ini tidak ada cara menentukan mana GR produksi;
            # jangan sampai `_action_done()` core ikut gagal karenanya.
            return

        todo = self.filtered(
            lambda ml: not ml.lot_id
            and ml.product_id.tracking != 'none'
            and ml.product_uom_id.compare(ml.quantity, 0) > 0
            and ml._is_gr_prod()
        )
        for ml in todo:
            lot = ml._get_or_create_lot()
            if not lot:
                raise ValidationError(
                    f"Lot untuk produk {ml.product_id.display_name} pada "
                    f"{ml.picking_id.name or ml.move_id.reference} tidak bisa dibuat "
                    "karena Line (Production Line) pada baris ini masih kosong.\n\n"
                    "Nama lot GR produksi dihasilkan dari format Production Code, "
                    "bukan dari barcode/QR yang di-scan."
                )
            ml.with_context(skip_lot_aft=True).write({'lot_id': lot.id, 'lot_name': False})

    def _create_and_assign_production_lot(self):
        """Jaring pengaman terakhir: GR produksi tidak boleh lewat jalur core.

        `_ensure_gr_prod_lot()` seharusnya sudah mengisi `lot_id` sebelum core
        sampai ke sini, tapi method ini juga dipanggil dari luar `_action_done`
        oleh modul lain -- kalau itu terjadi, nama lot tetap harus datang dari
        `_get_or_create_lot()`.
        """
        gr_prod = self.filtered(lambda ml: ml._is_gr_prod())
        if gr_prod:
            gr_prod._ensure_gr_prod_lot()
        others = self - gr_prod
        if others:
            return super(InheritBaseStockMoveLine, others)._create_and_assign_production_lot()

    # untuk stock.lot.aft ngurangin yang UU
    def _action_done(self):
        self._ensure_gr_prod_lot()
        # Kesempatan terakhir sebelum quant tujuan dibuat: baris yang waktu
        # `create()` belum menemukan quant apa pun (barangnya baru di-unpack ke
        # bin itu belakangan) diisi dari quant sumber yang sekarang jelas ada.
        # Tanpa ini `_propagate_stock_type_to_quants()` melewatinya dan quant di
        # package tujuan lahir tanpa stock_type.
        self.filtered(lambda ml: not ml.stock_type)._refresh_quant_inherited_fields()
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