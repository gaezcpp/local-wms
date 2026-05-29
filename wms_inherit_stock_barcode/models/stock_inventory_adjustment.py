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
    user_id = fields.Many2one(comodel_name='res.users', string="User", default=lambda self:self.env.user)
    location_id = fields.Many2one(comodel_name='stock.location', index=True)
    company_id = fields.Many2one(comodel_name='res.company', default=lambda self:self.env.company, string="Company")
    date_time = fields.Datetime(string="Inventory Date", default=fields.Datetime.now())
    quant_id = fields.Many2one(comodel_name='stock.quant', string="Quant")
    quant_count = fields.Integer(compute='_compute_quant_count')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('done_counting', 'Done Counting'),
        ('done_sap', 'Done SAP'),
        ('cancelled', 'Cancelled')
    ], default='draft', string="State")
    notes = fields.Text(string="Notes")
    is_checked = fields.Boolean(string="Is Checked?", default=False)
    adjustment_line_ids = fields.One2many('stock.inventory.adjustment.line', 'stock_adjustment_id', ondelete='cascade')
    summary_line_ids = fields.One2many('stock.inventory.adjustment.summary', 'stock_adjustment_id', ondelete='cascade')
    product_ids = fields.Many2many('product.product', string="Product(s)")
    sap_synchronize = fields.Boolean(string="SAP Synchronize", default=False)
    
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
            _logger.info(f"CRON {cron_name} NOT SUCCESS")
            return []

        data_list = res.get('data', [])
        _logger.info(f"CRON {cron_name} - TOTAL DATA: {len(data_list)}")
        return data_list
    
    def check_details(self):
        Quant = self.env['stock.quant'].sudo()
        for rec in self:
            if rec.state != 'draft':
                continue

            rec.adjustment_line_ids.unlink()

            domain = [
                ('company_id', '=', rec.company_id.id),
            ]
            
            if rec.product_ids:
                domain.append(('product_id', 'in', rec.product_ids.ids))
            if rec.location_id:
                domain.append(('location_id', 'child_of', rec.location_id.id))
                
            summary_stock_types = rec.summary_line_ids.mapped('stock_type')
            summary_stock_types = [s for s in summary_stock_types if s]
            if summary_stock_types:
                domain.append(('stock_type', 'in', summary_stock_types))

            quant = Quant.search(domain)
            if not quant:
                raise ValidationError("Physical Inventory not found!")
            
            for q in quant:
                self.env['stock.inventory.adjustment.line'].create({
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
            
            rec.is_checked = True
    
    def action_in_progress(self):
        for rec in self:
            if rec.state == 'draft':
                if not rec.is_checked:
                    raise ValidationError("Details dan Operations belum terisi, silahkan lakukan Get Details terlebih dahulu!")
                if not rec.adjustment_line_ids or len(rec.adjustment_line_ids) <= 0:
                    raise ValidationError("Minimal ada 1 Details untuk melakukan Progress")
                
                rec.state = 'in_progress'
    
    def action_done_counting(self):
        for rec in self:
            if rec.state != 'in_progress':
                continue

            SummaryModel = self.env['stock.inventory.adjustment.summary'].sudo()
            
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

                key = line.product_id.id
                if key not in summary_map:
                    summary_map[key] = {
                        'stock_adjustment_id': rec.id,
                        'product_id': line.product_id.id,
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

            for product_id, vals in summary_map.items():
                existing = SummaryModel.search([
                    ('stock_adjustment_id', '=', rec.id),
                    ('product_id', '=', product_id),
                ], limit=1)

                if existing:
                    existing.write({
                        'quantity': vals['quantity'],
                        'inventory_quantity': vals['inventory_quantity'],
                        'bag_qty': vals['bag_qty'],
                        'bag_count': vals['bag_count'],
                        'inventory_diff_quantity': vals['inventory_diff_quantity'],
                    })
                else:
                    SummaryModel.create(vals)

            rec.state = 'done_counting'
    
    def action_done_sap(self):
        for rec in self:
            if rec.state == 'done_counting':
                rec.state = 'done_sap'

    def action_cancelled(self):
        for rec in self:
            if rec.state in ('draft', 'in_progress'):
                rec.state = 'cancelled'

    def _compute_quant_count(self):
        Quant = self.env['stock.quant'].sudo()
        for rec in self:
            if not rec.adjustment_line_ids:
                rec.quant_count = 0
                continue
            domain = [('company_id', '=', rec.company_id.id),]
            
            if rec.product_ids:
                domain.append(('product_id', 'in', rec.product_ids.ids))
            if rec.location_id:
                domain.append(('location_id', 'child_of', rec.location_id.id))
            
            rec.quant_count = Quant.search_count(domain)
    
    def action_view_quant(self):
        self.ensure_one()
        domain = [('company_id', '=', self.company_id.id),]
        
        if self.product_ids:
            domain.append(('product_id', 'in', self.product_ids.ids))
        if self.location_id:
            domain.append(('location_id', 'child_of', self.location_id.id))
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Physical Inventory',
            'view_mode': 'list',
            'res_model': 'stock.quant',
            'domain': domain,
        }
    
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

    # Ini yang ngarah ke kanban dan auto scan | old yang pakai quant
    # def action_open_kanban_barcode(self):
    #     self.ensure_one()
    #     return {
    #         'type': 'ir.actions.act_window',
    #         'name': 'Stock Opname',
    #         'view_mode': 'kanban',
    #         'res_model': 'stock.inventory.adjustment',
    #         'domain': [
    #             ('id', '=', self.id),
    #         ],
    #     }
    
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
            
    @api.model
    def cron_synchronize_auto_done_pid(self):
        data_list = self._fetch_sap_data(
            config_key='query_pid_sap',
            cron_name='cron_synchronize_auto_done_pid',
        )
        if not data_list:
            return True
        _logger.info(f"TOTAL DATA cron_synchronize_auto_done_pid: {len(data_list)}")
        
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
            sia = sia_model.search([('pid_sap', '=', iblnr)])