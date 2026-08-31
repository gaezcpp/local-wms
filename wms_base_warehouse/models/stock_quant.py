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
    ], string="Stock Type", index=True)
    production_line_id = fields.Many2one(comodel_name='production.line', string="Line")
    is_available_qty_minus = fields.Boolean(string="Qty Minus", compute="_compute_is_available_qty_minus", store=True)

    @api.depends('reserved_quantity')
    def _compute_is_available_qty_minus(self):
        for quant in self:
            quant.is_available_qty_minus = (quant.available_quantity < 0)
    
    @api.model
    def _gather(self, product_id, location_id, lot_id=None, package_id=None, owner_id=None, strict=False, qty=None):
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
                lambda q: q.stock_type == 'UU' and q.package_id and q.package_id.yellow_tag == 'ready'
            )

        quants = quants.sorted(key=lambda q: 0 if q.package_id and q.package_id.pallet_status == 'eceran' else 1)

        return quants
    
    # Ini UNTUK BEGINNING STOCK
    def _get_upload_stock_companies(self):
        Company = self.env['res.company'].sudo()
        icp = self.env['ir.config_parameter'].sudo()

        upload_stock = (icp.get_param('upload_stock') or '').strip().lower()
        if upload_stock not in ('true', '1', 'yes'):
            return Company

        registries = [
            reg.strip()
            for reg in (icp.get_param('company_upload_stock') or '').split(',')
            if reg.strip()
        ]
        if not registries:
            _logger.warning(
                "upload_stock aktif tapi company_upload_stock kosong, "
                "logika beginning stock dilewati."
            )
            return Company

        companies = Company.search([('company_registry', 'in', registries)])
        if not companies:
            _logger.warning(
                "company_upload_stock %s tidak cocok dengan company_registry "
                "manapun di res.company, logika beginning stock dilewati.",
                registries,
            )
        return companies

    # Ini UNTUK BEGINNING STOCK
    def _filter_upload_stock(self):
        companies = self._get_upload_stock_companies()
        if not companies:
            return self.browse()
        return self.filtered(lambda quant: quant.company_id in companies)

    # Ini UNTUK BEGINNING STOCK
    @api.model
    def _get_inventory_fields_write(self):
        fields = super(StockQuant, self)._get_inventory_fields_write()
        if 'stock_type' not in fields:
            fields.append('stock_type')
        return fields
    
    @api.model
    def _get_inventory_fields_create(self):
        fields = super(StockQuant, self)._get_inventory_fields_create()
        if 'stock_type' not in fields:
            fields.append('stock_type')
        return fields
    
    # Ini UNTUK BEGINNING STOCK
    def action_apply_inventory(self, *args, **kwargs):
        pre_apply_types = {q.id: q.stock_type for q in self}
        res = super(StockQuant, self).action_apply_inventory(*args, **kwargs)

        additional_keys = set()
        allowed_quants = self._filter_upload_stock()
        for quant in allowed_quants:
            old_type = pre_apply_types.get(quant.id)
            if quant.stock_type != old_type:
                additional_keys.add((quant.lot_id.id, old_type))
                quant.with_context(inventory_mode=False).write({'stock_type': old_type})

        allowed_quants._sync_to_lot_aft(additional_keys)
        return res

    def write(self, vals):
        # Hanya dibutuhkan kalau stock_type memang ikut ditulis; membacanya di
        # setiap write (termasuk write quantity dari _action_done) berarti
        # memuat kolom untuk seluruh recordset tanpa dipakai.
        old_values = (
            {quant.id: quant.stock_type for quant in self}
            if 'stock_type' in vals else {}
        )
        res = super().write(vals)

        # Ini UNTUK BEGINNING STOCK
        additional_keys = set()
        if 'quantity' in vals or 'stock_type' in vals:
            allowed_quants = self._filter_upload_stock()
            if 'stock_type' in vals:
                for quant in allowed_quants:
                    old_type = old_values.get(quant.id)
                    if old_type and old_type != quant.stock_type:
                        additional_keys.add((quant.lot_id.id, old_type))

            if not self.env.context.get('inventory_mode'):
                allowed_quants._sync_to_lot_aft(additional_keys)

        if 'stock_type' in vals:
            self._log_stock_type_change(old_values)
            
        return res

    # Ini UNTUK BEGINNING STOCK
    def _sync_to_lot_aft(self, additional_keys=None):
        stock_lot_aft = self.env['stock.lot.aft'].sudo()
        keys_to_process = set()

        allowed_quants = self._filter_upload_stock()
        if not allowed_quants and not additional_keys:
            return

        for quant in allowed_quants:
            if not quant.lot_id or not quant.stock_type:
                continue
            keys_to_process.add((quant.lot_id.id, quant.stock_type))
                
        if additional_keys:
            for lot_id_id, old_type in additional_keys:
                if lot_id_id and old_type:
                    keys_to_process.add((lot_id_id, old_type))
                    
        for lot_id_id, stock_type in keys_to_process:
            related_quants = self.env['stock.quant'].search([
                ('lot_id', '=', lot_id_id),
                ('stock_type', '=', stock_type),
                ('location_id.usage', '=', 'internal')
            ])
            
            total_qty = sum(q.inventory_quantity if q.inventory_quantity > 0 else q.quantity for q in related_quants)
            
            match_lot_aft = stock_lot_aft.search([
                ('lot_id', '=', lot_id_id),
                ('stock_type', '=', stock_type)
            ], limit=1)
            
            if not match_lot_aft and total_qty <= 0:
                continue
                
            total_bag_qty = 0.0
            uom_id = False
            uom_bag_id = False
            
            if related_quants:
                first_q = related_quants[0]
                uom_id = first_q.product_uom_id.id if first_q.product_uom_id else False
                uom_bag_id = first_q.uom_bag_id.id if first_q.uom_bag_id else False
                if first_q.product_uom_id and first_q.uom_bag_id:
                    total_bag_qty = first_q.product_uom_id._compute_quantity(total_qty, first_q.uom_bag_id)
            elif match_lot_aft:
                uom_id = match_lot_aft.uom_id.id if match_lot_aft.uom_id else False
                uom_bag_id = match_lot_aft.uom_bag_id.id if match_lot_aft.uom_bag_id else False
            
            vals_aft = {
                'quantity': total_qty,
                'bag_qty': total_bag_qty,
            }
            if uom_id:
                vals_aft['uom_id'] = uom_id
            if uom_bag_id:
                vals_aft['uom_bag_id'] = uom_bag_id
                
            if match_lot_aft:
                match_lot_aft.write(vals_aft)
            else:
                vals_aft.update({
                    'lot_id': lot_id_id,
                    'stock_type': stock_type,
                })
                stock_lot_aft.create(vals_aft)

    def _log_stock_type_change(self, old_values):
        """Catat perubahan `stock_type` ke chatter pallet.

        Dua kejadian yang berbeda dibedakan bunyinya:

        * **quant baru** (`old_type` kosong). Setiap kali barang pindah lokasi,
          quant di lokasi asal dikosongkan dan quant BARU dibuat di lokasi
          tujuan -- lahir tanpa `stock_type`, lalu diisi
          `stock.move._propagate_stock_type_to_quants()` di transaksi yang sama.
          Jadi ini bukan perubahan status barang, cuma pencatatan pertama pada
          quant baru itu. Dulu bunyinya "diubah dari [-] menjadi [UU]" dan
          terbaca seolah status barang berubah; padahal 78% pesan di chatter
          adalah kejadian rutin ini.
        * **perubahan nyata** (`old_type` ada isinya): release QI -> UU, hold
          UU -> BLOCKED, dan sejenisnya.

        Keterangan "diwarisi dari quant asal" HANYA dipasang kalau pemanggil
        menyatakannya lewat context `stock_type_from_source_quant` --
        dipasang `stock.move._propagate_stock_type_to_quants()` untuk baris
        non-GR, yang nilainya memang datang dari quant sumber (lewat
        `_prepare_move_line_vals()` atau `_fill_from_source_quant()`). Pada GR
        produksi nilainya dipasang eksplisit QI oleh
        `stock.move.line._apply_gr_prod_stock_type()` -- tidak ada quant asal
        yang dibaca -- begitu pula penulisan dari adjustment/import, jadi
        keduanya memakai bunyi netral.
        """
        from_source_quant = self.env.context.get('stock_type_from_source_quant')
        for quant in self:
            old_type = old_values.get(quant.id)
            new_type = quant.stock_type
            if old_type == new_type or not quant.package_id:
                continue

            if old_type:
                # `new_type` bisa kosong kalau stock_type memang dihapus --
                # ditulis '-' supaya pesannya tidak berbunyi "menjadi [False]".
                message_body = (
                    f"Update Stock Type: Produk {quant.product_id.display_name} "
                    f"telah diubah dari [{old_type}] menjadi [{new_type or '-'}]."
                )
            else:
                asal = " diwarisi dari quant asal" if from_source_quant else ""
                message_body = (
                    f"Quant baru terbentuk: Produk {quant.product_id.display_name} "
                    f"masuk dengan Stock Type [{new_type}]{asal}."
                )
            quant.package_id.message_post(body=message_body)
    
    @api.model
    def fill_zero_bag(self):
        zero_bag = self.env['stock.quant'].sudo().search([('quantity', '>=', 1),('bag_qty', '=', 0)])
        for z in zero_bag:
            if z.product_uom_id and z.uom_bag_id:
                z.bag_qty = z.product_uom_id._compute_quantity(z.quantity, z.uom_bag_id)