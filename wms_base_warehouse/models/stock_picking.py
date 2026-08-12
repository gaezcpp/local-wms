from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
from datetime import datetime
from collections import defaultdict
import requests
import json
import logging
_logger = logging.getLogger(__name__)

class InheritBaseStockPicking(models.Model):
    _inherit = 'stock.picking'
    
    over_delivery = fields.Boolean(string="Over Delivery", tracking=True)
    production_shift_id = fields.Many2one(comodel_name='production.shift', string="Shift", tracking=True, index=True)
    production_order_name = fields.Char(string="Production Order", tracking=True)
    product_packaging_ids = fields.One2many('picking.packaging.line', 'picking_id')
    synchronize_sap = fields.Boolean(string="Synchronize SAP", default=False, tracking=True)
    production_only = fields.Boolean(related='picking_type_id.production_only', store=True, readonly=True)
    sloc_to = fields.Char(string="SLOC To")
    
    def _create_backorder(self, backorder_moves=None):
        backorders = super()._create_backorder(backorder_moves=backorder_moves)
        for backorder in backorders:
            if backorder.picking_type_id.show_entire_packs:
                backorder.do_unreserve()
                backorder.action_assign()
            backorder.write({'synchronize_sap': False})
        return backorders
    
    def copy(self, default=None):
        default = dict(default or {})
        default['synchronize_sap'] = False
        return super().copy(default)
    
    def _needs_update(self, model, vals):
        for field, new_val in vals.items():
            if field not in model._fields:
                continue

            field_def = model._fields[field]
            old_val = model[field]

            if field_def.type == 'many2one':
                old_id = old_val.id if old_val else False
                if old_id != new_val:
                    return True

            elif field_def.type in ('many2many', 'one2many'):
                if isinstance(new_val, list):
                    new_ids = set()
                    for cmd in new_val:
                        if cmd[0] == 6:
                            new_ids = set(cmd[2])
                        elif cmd[0] == 4:
                            new_ids.add(cmd[1])
                    old_ids = set(old_val.ids)
                    if old_ids != new_ids:
                        return True
                else:
                    if set(old_val.ids) != set(new_val):
                        return True

            else:
                if (old_val or False) != (new_val or False):
                    return True

        return False
    
    def _is_gr_prod(self):
        self.ensure_one()
        prod_in_move_type = self.env['ir.config_parameter'].sudo().get_param('prod_in_move_type')
        if not prod_in_move_type:
            raise ValidationError("prod_in_move_type pada Operation Type belum disetting!")
        
        return self.picking_type_id.move_type_sap == str(prod_in_move_type)

    def _check_restrict_over_demand(self):
        for picking in self:
            if not picking.picking_type_id.restrict_over_demand:
                continue

            for move in picking.move_ids:
                processed_qty = move.quantity
                demand_qty = move.product_uom_qty

                if processed_qty > demand_qty:
                    raise ValidationError("Tidak bisa melanjutkan proses dikarenakan quantity melebihi demand!")

    def button_validate(self):
        self._check_restrict_over_demand()
        res = super(InheritBaseStockPicking, self).button_validate()
        if isinstance(res, dict):
            return res

        for picking in self:
            if not picking._is_gr_prod() or picking.state != 'done':
                continue

            lot_updates = {}
            for move_line in picking.move_line_ids:
                if not move_line.move_id.product_id or not move_line.production_line_id:
                    continue
                
                lot = move_line.lot_id
                if not lot:
                    continue

                stype = move_line.stock_type or 'QI' # INI BIAR OTOMATIS QI SAAT GR
                # stype = move_line.stock_type
                if not stype:
                    picking.message_post(body=f"Move Line StockType Kosong")
                
                bag = move_line.bag_qty
                if bag <= 0 and move_line.uom_bag_id.factor:
                    bag = ((move_line.quantity * move_line.product_uom_id.factor) / 1000) / (move_line.uom_bag_id.factor / 1000)

                if lot not in lot_updates:
                    lot_updates[lot] = {}
                if stype not in lot_updates[lot]:
                    lot_updates[lot][stype] = {
                        'qty': 0.0,
                        'bag': 0.0,
                        'uom': move_line.product_uom_id,
                        'bag_uom': move_line.uom_bag_id
                    }
                
                lot_updates[lot][stype]['qty'] += move_line.quantity
                lot_updates[lot][stype]['bag'] += bag

            for lot, stype_data in lot_updates.items():
                ref_data = list(stype_data.values())[0]
                stock_types = ['QI', 'UU', 'BLOCKED']
                for st in stock_types:
                    aft_exists = self.env['stock.lot.aft'].sudo().search([
                        ('lot_id', '=', lot.id),
                        ('stock_type', '=', st)
                    ], limit=1)
                    
                    if not aft_exists:
                        self.env['stock.lot.aft'].create({
                            'lot_id': lot.id,
                            'quantity': 0.0,
                            'uom_id': ref_data['uom'].id,
                            'bag_qty': 0.0,
                            'uom_bag_id': ref_data['bag_uom'].id,
                            'stock_type': st,
                        })

                for stype, vals in stype_data.items():
                    target_aft = self.env['stock.lot.aft'].sudo().search([
                        ('lot_id', '=', lot.id),
                        ('stock_type', '=', stype)
                    ], limit=1)
                    
                    old_qty = target_aft.quantity
                    old_bag = target_aft.bag_qty
                    new_qty = old_qty + vals['qty']
                    new_bag = old_bag + vals['bag']

                    target_aft.write({
                        'quantity': new_qty,
                        'bag_qty': new_bag,
                    })

                    lot.message_post(body=(
                        f"Update Stock Type: {stype} ({picking.name}), Quantity: {old_qty} → {new_qty} {vals['uom'].name}, Bag Qty: {old_bag} → {new_bag} {vals['bag_uom'].name}"
                    ))

        return res

    # def action_cancel_done_picking(self, reason=False):
    #     """Force-cancel a stock.picking that already reached state='done'.

    #     Core Odoo refuses to cancel a done move (state stays consistent with
    #     quants/valuation only via a Return). This reverses the physical stock
    #     through the standard stock.return.picking mechanism first (which also
    #     unreserves the immediate downstream move via _do_unreserve, pushing it
    #     back to 'confirmed'/Waiting), then flips move_ids to 'cancel' so
    #     picking.state (computed from move states) settles on 'cancel' too.
    #     """
    #     for picking in self:
    #         if picking.state != 'done':
    #             raise ValidationError(
    #                 f"Picking {picking.name} tidak bisa dibatalkan karena statusnya "
    #                 f"'{picking.state}', bukan Done."
    #             )

    #         if not self.env.user.has_group('stock.group_stock_manager'):
    #             raise ValidationError("Hanya Stock Manager yang bisa membatalkan picking yang sudah Done.")

    #         downstream_done = picking.move_ids.move_dest_ids.filtered(lambda m: m.state == 'done')
    #         if downstream_done:
    #             raise ValidationError(
    #                 f"Tidak bisa membatalkan {picking.name} karena stock hasil transfer ini "
    #                 f"sudah diproses lebih lanjut di: "
    #                 f"{', '.join(downstream_done.picking_id.mapped('name'))}. "
    #                 f"Batalkan dahulu picking tersebut sebelum membatalkan {picking.name}."
    #             )

    #         if picking.picking_type_id.production_only and picking._is_gr_prod():
    #             raise ValidationError(
    #                 f"Tidak bisa membatalkan {picking.name} karena merupakan picking GR "
    #                 f"Production — reversal Stock Type (QI/UU/BLOCKED) pada stock.lot.aft "
    #                 f"belum didukung oleh fungsi ini."
    #             )

    #         return_wizard = self.env['stock.return.picking'].sudo().with_context(active_id=picking.id, active_model='stock.picking',).create({})
    #         return_action = return_wizard.action_create_returns_all()
    #         return_picking = self.env['stock.picking'].sudo().browse(return_action['res_id'])

    #         try:
    #             return_picking.with_context(skip_sanity_check=True).button_validate()
    #         except (ValidationError, UserError) as e:
    #             raise ValidationError(
    #                 f"Gagal membuat reversal stock otomatis untuk {picking.name}. "
    #                 f"Picking Return {return_picking.name} sudah dibuat tapi gagal divalidasi "
    #                 f"otomatis ({e}). Silahkan selesaikan {return_picking.name} secara manual "
    #                 f"terlebih dahulu."
    #             )

    #         if return_picking.state != 'done':
    #             raise ValidationError(
    #                 f"Gagal membuat reversal stock untuk {picking.name}. Picking Return "
    #                 f"{return_picking.name} berstatus '{return_picking.state}', bukan Done. "
    #                 f"Silahkan selesaikan secara manual."
    #             )

    #         moves_to_cancel = picking.move_ids.sudo()
    #         moves_to_cancel.write({'picked': False, 'state': 'cancel'})

    #         # Bebaskan next transfer (mis. Good Issue) dari referensi ke move yang
    #         # baru saja dibatalkan, supaya dia bisa reconnect ke stock manapun
    #         # yang tersedia berikutnya, bukan permanen "nunggu" move yang mati.
    #         for move in moves_to_cancel:
    #             dest_moves = move.move_dest_ids
    #             if not dest_moves:
    #                 continue
    #             siblings_states = (dest_moves.mapped('move_orig_ids') - move).mapped('state')
    #             if all(state in ('done', 'cancel') for state in siblings_states):
    #                 for dest_move in dest_moves:
    #                     dest_move.write({
    #                         'procure_method': 'make_to_stock',
    #                         'move_orig_ids': [(6, 0, (dest_move.move_orig_ids - move).ids)],
    #                     })

    #         picking.sudo().write({
    #             'is_locked': True,
    #             'synchronize_sap': False,
    #         })

    #         msg = f"Picking dibatalkan setelah Done oleh {self.env.user.name}. #cancel_done"
    #         if reason:
    #             msg += f" Alasan: {reason}"
    #         msg += f" Stock direversal melalui Return: {return_picking.name}."
    #         picking.message_post(body=msg)

    #     return True
    
    def action_revert_done_picking_to_draft(self, reason=False, auto_assign=False):
        """Force a done stock.picking back to state='draft' so it can be redone.

        Editing a done move_line's `quantity` is a natively-supported operation
        in core Odoo (see stock.move.line.write()): writing it to 0 makes core
        correctly reverse the exact quant movement _action_done() made
        (destination -> source) and automatically unreserve + re-trigger
        _action_assign() on any downstream move (e.g. Good Issue) that isn't
        done/cancel yet -- no separate Return document needed. Once the lines
        are gone and move_ids.state is 'draft', picking.state (computed from
        move_ids.state) settles on 'draft' too.

        If auto_assign is True, the picking is immediately re-confirmed and
        reserved (state -> 'assigned'/Ready) instead of being left in Draft.
        This does NOT affect any downstream transfer (e.g. Good Issue): it stays
        unreserved/Waiting until this picking is actually validated again.
        """
        for picking in self:
            if picking.state != 'done':
                raise ValidationError(
                    f"Picking {picking.name} tidak bisa dikembalikan ke Draft karena "
                    f"statusnya '{picking.state}', bukan Done."
                )

            if not self.env.user.has_group('base.group_system'):
                raise ValidationError(
                    "Hanya Admin yang bisa mengembalikan picking yang sudah Done ke Draft."
                )

            downstream_done = picking.move_ids.move_dest_ids.filtered(lambda m: m.state == 'done')
            if downstream_done:
                raise ValidationError(
                    f"Tidak bisa mengembalikan {picking.name} ke Draft karena stock hasil "
                    f"transfer ini sudah diproses lebih lanjut di: "
                    f"{', '.join(downstream_done.picking_id.mapped('name'))}. "
                    f"Selesaikan/batalkan dahulu picking tersebut sebelum mengembalikan "
                    f"{picking.name} ke Draft."
                )

            if picking.picking_type_id.production_only and picking._is_gr_prod():
                raise ValidationError(
                    f"Tidak bisa mengembalikan {picking.name} ke Draft karena merupakan "
                    f"picking GR Production — reversal Stock Type (QI/UU/BLOCKED) pada "
                    f"stock.lot.aft belum didukung oleh fungsi ini."
                )

            move_lines = picking.move_ids.move_line_ids.sudo()
            if move_lines:
                # quantity=0 pada move_line yang masih 'done' memicu core untuk
                # otomatis membalikkan quant (dest -> source) dan unreserve +
                # re-assign move tujuan (mis. Good Issue) yang belum done.
                move_lines.write({'quantity': 0})

            picking.move_ids.sudo().write({
                'state': 'draft',
                'picked': False,
                'date': fields.Datetime.now(),
            })

            # Sekarang state sudah 'draft' -> baris move_line lama (quantity
            # sudah 0) aman dihapus, supaya picking benar-benar seperti belum
            # pernah diproses.
            move_lines.unlink()

            picking.sudo().write({
                'synchronize_sap': False,
                'date_done': False,
            })

            if auto_assign:
                picking.action_confirm()
                picking.action_assign()

            msg = (
                f"Picking dikembalikan ke {'Ready' if auto_assign else 'Draft'} setelah "
                f"Done oleh {self.env.user.name}. #revert_to_draft"
            )
            if reason:
                msg += f" Alasan: {reason}"
            picking.message_post(body=msg)

        return True

    @api.model
    def _fetch_sap_data(self, config_key, cron_name):
        icp = self.env['ir.config_parameter'].sudo()
        x_i_api_key = icp.get_param('x_i_api_key')
        ip_sap_rfc = icp.get_param('ip_sap_rfc')
        query = icp.get_param(config_key)

        if not x_i_api_key:
            raise ValidationError("x_i_api_key belum disetting!")
        if not ip_sap_rfc:
            raise ValidationError("ip_sap_rfc belum disetting!")
        if not query:
            raise ValidationError(f"{config_key} belum disetting!")

        headers = {
            "x-i-api-key": str(x_i_api_key),
            "Content-Type": "application/json"
        }
        body = {
            "I_QUERY": str(query),
            "I_MOD": f"CRON {cron_name}"
        }
        try:
            response = requests.post(
                url=f"{ip_sap_rfc}/api/v1/zfm-query-data",
                headers=headers,
                data=json.dumps(body),
            )
        except Exception as e:
            raise ValidationError(str(e))

        res = response.json()
        if res.get('error'):
            raise ValidationError(json.dumps(res.get('error')))
        if not res.get('success'):
            _logger.info(f"CRON {cron_name} NOT SUCCESS || {res}")
            return []

        data_list = res.get('data', [])
        _logger.info(f"CRON {cron_name} - TOTAL DATA: {len(data_list)}")
        return data_list
    
    @api.model
    def cron_synhronize_sap_sales_return(self):
        sales_retur_barcode_sap = self.env['ir.config_parameter'].sudo().get_param('sales_retur_barcode_sap')
        data_list = self._fetch_sap_data(
            config_key='query_sales_return_sap',
            cron_name='cron_synhronize_sap_sales_return',
        )
        if not data_list:
            return True
        _logger.info(f"TOTAL DATA cron_synhronize_sap_sales_return: {len(data_list)}")
        
        picking_model = self.env['stock.picking'].sudo()
        move_model = self.env['stock.move'].sudo()
        wh_model = self.env['stock.warehouse'].sudo()
        operation_type_model = self.env['stock.picking.type'].sudo()
        partner_model = self.env['res.partner'].sudo()
        company_model = self.env['res.company'].sudo()
        product_model = self.env['product.product'].sudo()
        uom_model = self.env['uom.uom'].sudo()

        grouped_data = defaultdict(list)

        for row in data_list:
            vblen = row.get('VBLEN')
            if vblen:
                grouped_data[vblen].append(row)
        for vblen, rows in grouped_data.items():
            first = rows[0]
            werks = (first.get('WERKS') or '').strip()
            arrdate = (first.get('ARRDATE') or '').strip()
            lgort = (first.get('LGORT') or '').strip()
            trucknr = (first.get('TRUCKNR') or '').strip()
            kunnr = (first.get('KUNNR') or '').strip()
            bktxt = (first.get('BKTXT') or '').strip()
            note = '\n'.join(filter(None, [bktxt, trucknr]))
            
            company = company_model.search([('company_registry', '=', werks),('sync_wms', '=', True)], limit=1)
            if not company:
                _logger.info(f"cron_synhronize_sap_sales_return COMPANY {werks} SKIPPED")
                continue

            partner = partner_model.search([('ref', '=', kunnr)], limit=1)
            if not partner:
                _logger.info(f"cron_synhronize_sap_sales_return PARTNER {kunnr} SKIPPED")
                continue
            
            warehouse = wh_model.search([
                ('lot_stock_id.sloc_id.code', '=', lgort),
                ('company_id', '=', company.id),
            ], limit=1)
            if not warehouse:
                _logger.info(f"cron_synhronize_sap_sales_return WAREHOUSE lgort={lgort} SKIPPED")
                continue
            
            operation_type = operation_type_model.search([
                ('barcode', '=', str(sales_retur_barcode_sap)),
                ('warehouse_id', '=', warehouse.id),
                ('company_id', '=', company.id)
            ], limit=1)
            if not operation_type:
                _logger.info(f"cron_synhronize_sap_sales_return OPERATION TYPE {sales_retur_barcode_sap} SKIPPED")
                continue

            schedule_date = False
            if arrdate and len(arrdate) == 8:
                schedule_date = datetime.strptime(arrdate, "%Y%m%d")

            sales_return = picking_model.search([('origin', '=', vblen),('company_id', '=', company.id),('state', '!=', 'cancel')], limit=1)
            vals = {
                'partner_id': partner.id,
                'picking_type_id': operation_type.id,
                'location_dest_id': operation_type.default_location_dest_id.id,
                'synchronize_sap': True,
                'origin': vblen,
                'scheduled_date': schedule_date,
                'company_id': company.id,
                'note': note,
            }
            if not sales_return:
                sales_return = sales_return.create(vals)
                sales_return.message_post(body=f"SALES RETURN {vblen} Created from Cron")
                _logger.info(f"SALES RETURN {vblen}")
            else:
                if self._needs_update(sales_return, vals):
                    sales_return.write(vals)

            for row in rows:
                matnr = (row.get('MATNR') or '').lstrip('0')
                product = product_model.search([('default_code', '=', matnr), ('company_id', '=', company.id)], limit=1)
                if not product:
                    _logger.info(f"cron_synhronize_sap_sales_return PRODUCT {matnr} SKIPPED")
                    continue
                
                uom_bag = (row.get('VRKME') or '')
                umrez = float(row.get('UMREZ') or 1)
                umren = float(row.get('UMREN') or 1)
                product_uom = product.uom_bag_id
                if uom_bag and uom_bag.upper() != "KG":
                    ratio = float(umrez) / float(umren)
                    ratio = int(ratio) if ratio.is_integer() else ratio
                    uom_name = f"{uom_bag} {ratio}"
                    uom = uom_model.search([('name', '=', uom_name)], limit=1)
                    if uom:
                        product_uom = uom

                qty = float(row.get('DOQTY') or 0)
                posnr = (row.get('POSNR') or "").lstrip('0')
                existing_line = move_model.search([
                    ('picking_id', '=', sales_return.id),
                    ('product_id', '=', product.id),
                    ('sap_seq', '=', posnr),
                    ('order_seq', '=', posnr)
                ], limit=1)

                vals_line = {
                    'picking_id': sales_return.id,
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'quantity': qty,
                    'product_uom': product_uom.id,
                    'location_id': sales_return.location_id.id,
                    'location_dest_id': sales_return.location_dest_id.id,
                    'sap_seq': posnr,
                    'order_seq': posnr,
                    'company_id': company.id,
                }
                
                if existing_line:
                    if self._needs_update(existing_line, vals_line):
                        existing_line.write({'product_uom_qty': qty})
                else:
                    move_model.create(vals_line)

            _logger.info(f"SALES RETUR {vblen} total line {len(rows)}")