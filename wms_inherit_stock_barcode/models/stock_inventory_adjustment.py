from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools.safe_eval import safe_eval
from datetime import datetime
from collections import defaultdict
import requests
import json
import logging
import re
import pytz
_logger = logging.getLogger(__name__)

class StockInventoryAdjustment(models.Model):
    _name = 'stock.inventory.adjustment'
    _description = 'Stock Inventory Adjustment'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    
    name = fields.Char(string="Name", default="New")
    pid_sap = fields.Char(string="PID SAP")
    done_pid_number = fields.Char(string="Done PID")
    user_id = fields.Many2one(comodel_name='res.users', string="User", default=lambda self:self.env.user)
    location_id = fields.Many2one(comodel_name='stock.location', index=True)
    company_id = fields.Many2one(comodel_name='res.company', default=lambda self:self.env.company, string="Company")
    date_time = fields.Datetime(string="Inventory Date", default=fields.Datetime.now)
    quant_id = fields.Many2one(comodel_name='stock.quant', string="Quant")
    quant_count = fields.Integer(compute='_compute_quant_count')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('done_counting', 'Done Counting'),
        ('done_sap', 'Done SAP'),
        ('berita_acara', 'Berita Acara'),
        ('cancelled', 'Cancelled')
    ], default='draft', string="State", tracking=True)
    notes = fields.Text(string="Notes")
    is_checked = fields.Boolean(string="Is Checked?", default=False)
    adjustment_line_ids = fields.One2many('stock.inventory.adjustment.line', 'stock_adjustment_id', ondelete='cascade')
    summary_line_ids = fields.One2many('stock.inventory.adjustment.summary', 'stock_adjustment_id', ondelete='cascade')
    product_ids = fields.Many2many('product.product', string="Product(s)")
    sap_synchronize = fields.Boolean(string="SAP Synchronize", default=False)
    need_berita_acara = fields.Boolean(string="Need Berita Acara", default=False)
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('stock.inventory.adjustment') or _('New')
        res = super().create(vals_list)
        return res
    
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
    
    def check_details(self):
        Quant = self.env['stock.quant'].sudo()
        LineModel = self.env['stock.inventory.adjustment.line']
        for rec in self:
            if rec.state != 'draft':
                continue

            rec.adjustment_line_ids.unlink()

            domain = [('company_id', '=', rec.company_id.id)]
            
            if rec.location_id:
                domain.append(('location_id', 'child_of', rec.location_id.id))
            if rec.product_ids:
                domain.append(('product_id', 'in', rec.product_ids.ids))
                
            summary_stock_types = rec.summary_line_ids.mapped('stock_type')
            summary_stock_types = [s for s in summary_stock_types if s]
            if summary_stock_types:
                domain.append(('stock_type', 'in', summary_stock_types))

            quants = Quant.search(domain)
            if not quants:
                _logger.info("Physical Inventory Not Found for SIA %s", rec.name)
            
            vals_list = []
            for q in quants:
                vals_list.append({
                    'quant_id': q.id,
                    'stock_adjustment_id': rec.id,
                    'product_id': q.product_id.id,
                    'uom_id': q.product_uom_id.id,
                    'uom_bag_id': q.uom_bag_id.id,
                    'location_id': q.location_id.id,
                    'lot_id': q.lot_id.id if q.lot_id else False,
                    'package_id': q.package_id.id if q.package_id else False,
                    'package_status': q.stock_type or '',
                    'quantity': q.quantity,
                    'inventory_quantity': q.inventory_quantity,
                    'bag_qty': q.bag_qty,
                    'inventory_diff_quantity': q.inventory_diff_quantity,
                })
            
            if vals_list:
                LineModel.create(vals_list)
            
            rec.write({
                'is_checked': True,
                'state': 'in_progress' if len(rec.adjustment_line_ids) > 0 else 'draft'
            })
    
    def action_in_progress(self):
        for rec in self:
            if rec.state == 'draft':
                if not rec.is_checked:
                    raise ValidationError("Details dan Operations belum terisi, silahkan lakukan Get Details terlebih dahulu!")
                if not rec.adjustment_line_ids or len(rec.adjustment_line_ids) <= 0:
                    raise ValidationError("Minimal ada 1 Details untuk melakukan Progress")
                
                rec.state = 'in_progress'
    
    def action_done_counting(self):
        SummaryModel = self.env['stock.inventory.adjustment.summary'].sudo()
        for rec in self:
            if rec.state != 'in_progress':
                continue

            unapplied_lines = rec.adjustment_line_ids.filtered(lambda l: l.quant_id and not l.quant_id.inventory_quantity_set)
            if unapplied_lines:
                unapplied_products = unapplied_lines.mapped('product_id.display_name')
                raise ValidationError(
                    "Beberapa produk belum dilakukan Counting! Silahkan lakukan Counting terlebih dahulu!:\n- %s"
                    % "\n- ".join(unapplied_products)
                )

            summary_map = {}
            for line in rec.adjustment_line_ids:
                if not line.product_id:
                    continue

                key = (line.product_id.id, line.package_status)                
                if key not in summary_map:
                    summary_map[key] = {
                        'stock_adjustment_id': rec.id,
                        'product_id': line.product_id.id,
                        'stock_type': line.package_status,
                        'uom_id': line.uom_id.id if line.uom_id else False,
                        'uom_bag_id': line.uom_bag_id.id if line.uom_bag_id else False,
                        'quantity': 0.0,
                        'inventory_quantity': 0.0,
                        'bag_qty': 0.0,
                        'bag_count': 0.0,
                        'inventory_diff_quantity': 0.0,
                    }

                summary_map[key]['quantity'] += line.quantity or 0.0
                summary_map[key]['inventory_quantity'] += line.inventory_quantity or 0.0
                summary_map[key]['bag_qty'] += line.bag_qty or 0.0
                summary_map[key]['bag_count'] += line.bag_count or 0.0
                summary_map[key]['inventory_diff_quantity'] += line.inventory_diff_quantity or 0.0

            existing_summaries = SummaryModel.search([('stock_adjustment_id', '=', rec.id)])
            existing_map = {(s.product_id.id, s.stock_type): s for s in existing_summaries}
            
            new_summaries = []
            for key_tuple, vals in summary_map.items():
                if key_tuple in existing_map:
                    existing_map[key_tuple].write({
                        'quantity': vals['quantity'],
                        'inventory_quantity': vals['inventory_quantity'],
                        'bag_qty': vals['bag_qty'],
                        'bag_count': vals['bag_count'],
                        'inventory_diff_quantity': vals['inventory_diff_quantity'],
                    })
                else:
                    new_summaries.append(vals)
                    
            if new_summaries:
                SummaryModel.create(new_summaries)

            rec.state = 'done_counting'

    def action_cancelled(self):
        for rec in self:
            if rec.state in ('draft', 'in_progress'):
                rec.state = 'cancelled'
                
    def action_berita_acara(self):
        self.ensure_one()
        if not self.need_berita_acara:
            raise ValidationError("Berita Acara hanya bisa dilakukan jika ada Diff pada Summary")
        
        view = self.env.ref('wms_inherit_stock_barcode.pid_berita_acara_wizard_form_views')
        return {
            'type': 'ir.actions.act_window',
            'name': 'PID Berita Acara',
            'res_model': 'pid.berita.acara.wizard',
            'views': [(view.id, 'form')],
            'target': 'new',
            'context': {
                'default_sia_id': self.id,
            }
        }

    @api.depends('adjustment_line_ids', 'adjustment_line_ids.quant_id')
    def _compute_quant_count(self):
        for record in self:
            record.quant_count = len(record.adjustment_line_ids.mapped('quant_id'))
    
    def action_view_quant(self):
        self.ensure_one()

        list_view_id = self.env.ref('wms_inherit_stock_barcode.view_stock_quant_readonly_list').id
        quant_ids = self.adjustment_line_ids.mapped('quant_id').ids

        return {
            'type': 'ir.actions.act_window',
            'name': 'Physical Inventory',
            'view_mode': 'list',
            'views': [(list_view_id, 'list')],
            'res_model': 'stock.quant',
            'domain': [('id', 'in', quant_ids)],
            'context': {
                'create': False,
                'edit': False,
                'delete': False,
                'duplicate': False,
                'inventory_mode': False,
                'no_recompute': True,
            }
        }
    
    def apply_lot_aft_adjustment(self, sia):
        valid_lines = sia.adjustment_line_ids.filtered(lambda l: l.lot_id and l.package_status)
        if not valid_lines:
            return

        lot_ids = valid_lines.mapped('lot_id').ids
        stock_types = list(set(valid_lines.mapped('package_status')))
        
        existing_lot_afts = self.env['stock.lot.aft'].sudo().search([
            ('lot_id', 'in', lot_ids),
            ('stock_type', 'in', stock_types)
        ])
        
        lot_aft_map = {(la.lot_id.id, la.stock_type): la for la in existing_lot_afts}
        for line in valid_lines:
            lot_aft = lot_aft_map.get((line.lot_id.id, line.package_status))

            if not lot_aft:
                _logger.warning(f"lot_aft tidak ditemukan untuk lot {line.lot_id.name} stock_type {line.package_status}")
                continue

            lot_aft.write({
                'quantity': line.inventory_quantity,
                'bag_qty': line.bag_count,
            })
            _logger.info(
                "_apply_lot_aft_adjustment: lot %s stock_type %s → qty=%.3f bag=%.3f",
                line.lot_id.name, line.package_status,
                line.inventory_quantity, line.bag_count
            )
    
    # Ini yang auto scan
    def action_open_barcode_inventory(self):
        self.ensure_one()

        action = self.env['ir.actions.actions']._for_xml_id('stock_barcode.stock_barcode_inventory_client_action')
        action['context'] = {
            'active_id': False,
            'active_ids': [],
            'active_model': False,
            'default_location_barcode': self.location_id.barcode or '',
            'auto_submit_barcode': True,
        }
        
        print(f"action_open_barcode_inventory.action {action}")

        return action
    
    def action_open_kanban_barcode(self):
        self.ensure_one()
        return self.env.ref('stock_barcode.stock_barcode_action_main_menu').read()[0]
        
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
    
    # Ini buat testing
    def bypass_done_pid_sap(self):
        for rec in self:
            quant_ids = rec.adjustment_line_ids.mapped('quant_id').filtered(lambda q: q.id)
            if quant_ids:
                quants_to_apply = quant_ids.filtered(lambda q: q.inventory_quantity_set)
                if quants_to_apply:
                    stock_type_snapshot = {q.id: q.stock_type for q in quants_to_apply}
                    
                    self.apply_lot_aft_adjustment(rec)
                    quants_to_apply.action_apply_inventory()
                    
                    for q in quants_to_apply:
                        if q.id in stock_type_snapshot:
                            q.stock_type = stock_type_snapshot[q.id]
                            
                    _logger.info(f"cron_synchronize_auto_done_pid IBLNR {rec.name}: action_apply_inventory berhasil untuk {len(quants_to_apply)} quant.")
                    rec.write({
                        'need_berita_acara': True,
                        'state': 'done_sap',
                        'done_pid_number': 'BYPASS',
                    })
    
    @api.model
    def cron_synhronize_pid_sap(self):
        data_list = self._fetch_sap_data(
            config_key='query_pid_sap',
            cron_name='cron_synhronize_pid_sap',
        )
        if not data_list:
            return True
        _logger.info(f"TOTAL DATA cron_synhronize_pid_sap: {len(data_list)}")

        sia_model = self.env['stock.inventory.adjustment'].sudo()
        summary_sia_model = self.env['stock.inventory.adjustment.summary'].sudo()
        wh_model = self.env['stock.warehouse'].sudo()
        product_model = self.env['product.product'].sudo()
        unit_model = self.env['uom.uom'].sudo()
        company_model = self.env['res.company'].sudo()

        grouped_data = defaultdict(list)

        for row in data_list:
            iblnr = (row.get('IBLNR') or '')
            if iblnr:
                grouped_data[iblnr].append(row)
        for iblnr, rows in grouped_data.items():
            first = rows[0]
            lgort = (first.get('LGORT') or '').strip()
            werks = (first.get('WERKS') or '').strip()

            company = company_model.search([('company_registry', '=', werks),('sync_wms', '=', True)], limit=1)
            if not company:
                _logger.info(f"CRON cron_synhronize_pid_sap Company {werks} SKIPPED")
                continue
            
            matnr_list = list({row.get('MATNR') for row in rows if row.get('MATNR')})
            products = product_model.search([
                ('default_code', 'in', matnr_list),
                ('company_id', 'in', [company.id, False]),
            ])
            product_ids = [(6, 0, products.ids)]
            
            warehouse = wh_model.search([
                ('lot_stock_id.sloc_id.code', '=', lgort),
                ('company_id', '=', company.id),
            ], limit=1)
            if not warehouse:
                _logger.info(f"cron_synhronize_pid_sap sloc code {lgort} skipped")
                continue

            sia = sia_model.search([
                ('pid_sap', '=', iblnr),
                ('company_id', '=', company.id)
            ], limit=1)
            vals = {
                'sap_synchronize': True,
                'pid_sap': iblnr,
                'location_id': warehouse.lot_stock_id.id,
                'product_ids': product_ids,
                'company_id': company.id,
                'state': 'draft',
                'date_time': fields.Datetime.now(),
                'notes': "Created from Cron",
            }
            if not sia:
                sia = sia_model.create(vals)
                sia.message_post(body=f"Stock Inventory Adjustment SAP {iblnr} Created from Cron")
                _logger.info(f"Stock Inventory Adjustment Created {iblnr}")
            else:
                if self._needs_update(sia, vals):
                    sia.write(vals)

            for row in rows:
                product_code = (row.get('MATNR') or '').lstrip('0')
                product = product_model.search([
                    ('default_code', '=', product_code),
                    ('company_id', '=', company.id)
                ], limit=1)
                if not product:
                    _logger.info(f"cron_synhronize_pid_sap product not found {product_code} skipped")
                    continue
                
                meins = (row.get('MEINS') or '').strip().lower()
                uom = unit_model.search([('name', '=', meins)], limit=1)
                if not uom:
                    _logger.info(f"cron_synhronize_pid_sap uom not found {meins} skipped")
                    continue

                qty = float(row.get('MENGE') or 0)
                zeili = (row.get('ZEILI') or '').strip()
                existing_line = summary_sia_model.search([
                    ('stock_adjustment_id', '=', sia.id),
                    ('product_id', '=', product.id),
                    ('zeili', '=', zeili)
                ], limit=1)
                
                bstart = (row.get('BSTAR') or '').strip()
                if bstart == '1':
                    stock_type = 'UU'
                elif bstart == '2':
                    stock_type = 'QI'
                elif bstart == '3':
                    stock_type = False
                else:
                    stock_type = 'BLOCKED'

                vals_line = {
                    'stock_adjustment_id': sia.id,
                    'zeili': zeili,
                    'product_id': product.id,
                    'uom_id': uom.id,
                    'uom_bag_id': product.uom_bag_id.id,
                    'sloc_name': lgort,
                    'stock_type': stock_type,
                    'quantity': qty,
                }

                if existing_line:
                    if self._needs_update(existing_line, vals_line):
                        existing_line.write({'quantity': qty})
                else:
                    summary_sia_model.create(vals_line)

            _logger.info(f"SIA Summary {iblnr} total line {len(rows)}")
            
            if sia.state == 'draft': 
                sia.check_details()
            
    @api.model
    def cron_synchronize_auto_done_pid(self):
        data_list = self._fetch_sap_data(
            config_key='query_auto_done_pid_sap',
            cron_name='cron_synchronize_auto_done_pid',
        )
        if not data_list:
            return True

        _logger.info("TOTAL DATA cron_synchronize_auto_done_pid: %d", len(data_list))

        sia_model = self.env['stock.inventory.adjustment'].sudo()
        company_model = self.env['res.company'].sudo()

        grouped_data = defaultdict(list)
        for row in data_list:
            iblnr = (row.get('IBLNR') or '').strip()
            if iblnr:
                grouped_data[iblnr].append(row)

        for iblnr, rows in grouped_data.items():
            first = rows[0]
            mblnr = (first.get('MBLNR') or '').strip()
            werks = (first.get('WERKS') or '').strip()

            if not mblnr:
                _logger.info(f"cron_synchronize_auto_done_pid IBLNR {iblnr} SKIPPED")
                continue

            company = company_model.search([
                ('company_registry', '=', werks),
                ('sync_wms', '=', True),
            ], limit=1)
            if not company:
                _logger.info(f"cron_synchronize_auto_done_pid COMPANY {werks} SKIPPED")
                continue

            sia = sia_model.search([
                ('pid_sap', '=', iblnr),
                ('company_id', '=', company.id),
                ('state', '=', 'done_counting'),
            ], limit=1)
            if not sia:
                _logger.info(f"cron_synchronize_auto_done_pid {iblnr} tidak ditemukan atau bukan done_counting, SKIPPED.")
                continue

            quant_ids = sia.adjustment_line_ids.mapped('quant_id').filtered(lambda q: q.id)
            if quant_ids:
                quants_to_apply = quant_ids.filtered(lambda q: q.inventory_quantity_set)
                if quants_to_apply:
                    self.apply_lot_aft_adjustment(sia) # Update lot qty by stocktype
                    quants_to_apply.action_apply_inventory()
                    _logger.info(f"cron_synchronize_auto_done_pid IBLNR {iblnr}: action_apply_inventory berhasil untuk {len(quants_to_apply)} quant.")
                else:
                    _logger.warning(f"cron_synchronize_auto_done_pid IBLNR {iblnr}: Tidak ada quant dengan inventory_quantity_set=True.")
            else:
                _logger.warning(f"cron_synchronize_auto_done_pid IBLNR {iblnr}: Tidak ada quant terkait pada SIA {sia.name}")

            need_ba = bool(sia.summary_line_ids.filtered(lambda s: s.inventory_diff_quantity != 0.0))
            sia.write({
                'state': 'done_sap',
                'done_pid_number': mblnr,
                'need_berita_acara': need_ba
            })
            sia.message_post(body=f"Inventory applied & status Done SAP via cron. IBLNR: {iblnr}, MBLNR: {mblnr}")