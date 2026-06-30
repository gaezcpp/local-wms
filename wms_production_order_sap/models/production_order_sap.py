from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import datetime
from collections import defaultdict
import requests
import json
import logging
import pytz
_logger = logging.getLogger(__name__)

class ProductionOrderSAP(models.Model):
    _name = 'production.order.sap'
    _description = 'Production Order SAP'
    _rec_name = 'po_number'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    po_number = fields.Char(string="Production Order", tracking=True)
    order_type = fields.Char(string="Order Type", tracking=True)
    start_date = fields.Date(string="Start Date", tracking=True)
    finish_date = fields.Date(string="Finish Date", tracking=True)
    product_id = fields.Many2one(comodel_name='product.product', string="Product", tracking=True)
    uom_id = fields.Many2one(comodel_name='uom.uom', string="UoM", tracking=True)
    order_qty = fields.Float(string="Order Qty", tracking=True)
    company_registry = fields.Char(string="Company Registry", tracking=True)
    company_id = fields.Many2one(comodel_name='res.company', string="Company", default=lambda self: self.env.company, tracking=True)
    state = fields.Selection([
        ('open', 'Open'),
        ('in_progress', 'In Progress'),
        ('teco', 'TECO'),
    ], string="Status", default='open', tracking=True)
    created_user = fields.Char(string="Created By", tracking=True)
    status_teco = fields.Char(string="TECO Status", tracking=True)
    sap_pp = fields.Boolean(string="SAP PP", default=False)
    active = fields.Boolean(string="Active", default=True)
    picking_count = fields.Integer(string="Picking Count", compute='_compute_picking_count')
    gr_bag_qty = fields.Float(string="GR Bag", compute='_compute_gr_qty', store=True)
    gr_kg_qty = fields.Float(string="GR Kg", compute='_compute_gr_qty', store=True)
    picking_ids = fields.One2many('stock.picking', 'po_sap_id', string="Pickings")
    remaining_qty = fields.Float(string="Remaining", compute='_compute_gr_qty', store=True)
    po_sap_line_ids = fields.One2many('production.order.sap.line', 'po_sap_id')

    @api.depends('picking_ids.state', 'picking_ids.move_ids.quantity', 'order_qty')
    def _compute_gr_qty(self):
        for po in self:
            done_moves = po.sudo().picking_ids.filtered(
                lambda p: p.state == 'done' and p.location_dest_id.id == p.picking_type_id.warehouse_id.lot_stock_id.id
            ).mapped('move_ids').filtered(lambda m: m.state == 'done')

            po.gr_bag_qty = sum(done_moves.mapped('bag_qty'))
            po.gr_kg_qty = sum(done_moves.mapped('quantity'))
            po.remaining_qty = po.order_qty - po.gr_kg_qty
    
    def _compute_picking_count(self):
        domain = [('po_sap_id', 'in', self.ids),('state', 'not in', ('done', 'cancel'))]
        groups = self.env['stock.picking'].sudo()._read_group(
            domain=domain,
            groupby=['po_sap_id'],
            aggregates=['__count'],
        )
        count_map = {po_sap.id: count for po_sap, count in groups}
        for rec in self:
            rec.picking_count = count_map.get(rec.id, 0)
        
    def action_smart_picking_po_sap(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Picking',
            'view_mode': 'kanban,list,form',
            'res_model': 'stock.picking',
            'domain': [('po_sap_id', '=', self.id),('state', 'not in', ('done', 'cancel'))],
            'context': {
                'create': 0,
                'edit': 0,
                'delete': 0,
                'duplicate': 0,
            }
        }
        
    def today_jakarta(self):
        tz = pytz.timezone('Asia/Jakarta')
        now_jakarta = datetime.now(tz)
        return now_jakarta.date()
    
    def now_jakarta(self):
        tz = pytz.timezone('Asia/Jakarta')
        return datetime.now(tz)
    
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
    
    # @api.model
    # def cron_synchronize_sap_production_order(self):
    #     data_list = self._fetch_sap_data(
    #         config_key='query_production_order_sap',
    #         cron_name='cron_synchronize_sap_production_order',
    #     )
    #     if not data_list:
    #         return True
    #     _logger.info(f"TOTAL DATA cron_synchronize_sap_production_order: {len(data_list)}")
        
    #     po_sap = self.env['production.order.sap'].sudo()
    #     companies = self.env['res.company'].sudo()
    #     product_template = self.env['product.product'].sudo()
    #     unit_of_measure = self.env['uom.uom'].sudo()
    #     for data in data_list:
    #         po_number = data.get('AUFNR')
    #         if not po_number:
    #             continue
            
    #         order_type = data.get('AUART') or ''
    #         company_registry = data.get('WERKS') or ''
    #         if company_registry:
    #             company_id = companies.search([
    #                 ('company_registry', '=', company_registry),
    #                 ('sync_wms', '=', True),
    #             ], limit=1)
    #             if not company_id:
    #                 _logger.info(f"cron_synchronize_sap_production_order COMPANY: {company_registry} SKIPPED")
    #                 continue
            
    #         product_code = (data.get('MATNR') or '').lstrip('0')
    #         if product_code:
    #             product_id = product_template.search([('default_code', '=', product_code),('company_id', '=', company_id.id)], limit=1)
    #             if not product_id:
    #                 _logger.info(f"cron_synchronize_sap_production_order PRODUCT: {product_code} SKIPPED")
    #                 continue
                
    #         unit = data.get('GMEIN') or ''
    #         product_uom = False
    #         if unit.upper() != "KG":
    #             raw_umrez = str(data.get('UMREZ') or '').strip()
    #             uom_numerator = float(raw_umrez if raw_umrez else 0.0)
                
    #             raw_umren = str(data.get('UMREN') or '').strip()
    #             uom_denominator = float(raw_umren if raw_umren else 0.0)
                
    #             ratio = (uom_numerator / uom_denominator) if uom_denominator else 0.0
    #             ratio = int(ratio) if ratio.is_integer() else ratio
    #             uom_name = f"{unit} {ratio}"
    #             product_uom = unit_of_measure.search([('name', '=', uom_name)], limit=1)
    #         else:
    #             product_uom = unit_of_measure.search([('name', '=', 'kg')], limit=1)
            
    #         start_date = False
    #         finish_date = False
    #         raw_start = data.get('GSTRP')
    #         if raw_start and len(raw_start) == 8:
    #             start_date = datetime.strptime(raw_start, "%Y%m%d").date()

    #         raw_finish = data.get('GLTRP')
    #         if raw_finish and len(raw_finish) == 8:
    #             finish_date = datetime.strptime(raw_finish, "%Y%m%d").date()
            
    #         raw_gamng = str(data.get('GAMNG') or '').strip()
    #         order_qty = float(raw_gamng if raw_gamng else 0.0)
    #         created_user = data.get('ERNAM') or ''
    #         teco_status = (data.get('TECO_STATUS') or '').strip().upper()
    #         loekz = (data.get('LOEKZ') or '').strip()
            
    #         vals = {
    #             'po_number': po_number,
    #             'order_type': order_type,
    #             'start_date': start_date,
    #             'finish_date': finish_date,
    #             'product_id': product_id.id if product_id else False,
    #             'uom_id': product_uom.id if product_uom else False,
    #             'order_qty': order_qty,
    #             'company_id': company_id.id if company_id else False,
    #             'company_registry': company_id.company_registry if company_id else False,
    #             'status_teco': teco_status,
    #             'created_user': created_user,
    #             'sap_pp': True,
    #             'active': loekz != 'X',
    #         }
            
    #         existing_po_sap = po_sap.search([('po_number', '=', po_number)], limit=1)
    #         if not existing_po_sap:
    #             new_po = po_sap.create(vals)
    #             new_po.message_post(body=f"PO SAP {new_po.po_number} Created from Cron")
    #             _logger.info(f"PO SAP {new_po.po_number} Created")
    #         else:
    #             if self._needs_update(existing_po_sap, vals):
    #                 existing_po_sap.write(vals)
    #                 _logger.info(f"PO {existing_po_sap.po_number} Updated")
                
    #             if teco_status == 'TECO':
    #                 if existing_po_sap.state != 'teco':
    #                     existing_po_sap.write({'state': 'teco', 'status_teco': 'TECO'})
    #             else:
    #                 if existing_po_sap.state != 'teco':
    #                     existing_po_sap.write({'state': 'in_progress', 'status_teco': 'NOT TECO'})
    
    @api.model
    def cron_synchronize_sap_production_order(self):
        data_list = self._fetch_sap_data(
            config_key='query_production_order_sap',
            cron_name='cron_synchronize_sap_production_order',
        )
        if not data_list:
            return True
        _logger.info(f"TOTAL DATA cron_synchronize_sap_production_order: {len(data_list)}")
        
        po_sap_model = self.env['production.order.sap'].sudo()
        po_sap_line_model = self.env['production.order.sap.line'].sudo()
        company_model = self.env['res.company'].sudo()
        product_model = self.env['product.product'].sudo()
        uom_model = self.env['uom.uom'].sudo()
        
        grouped_data = defaultdict(list)
        for row in data_list:
            po_number = row.get('AUFNR') or ''
            if not po_number:
                continue
            grouped_data[po_number].append(row)
            
        for po_number, rows in grouped_data.items():
            first = rows[0]
            order_type = first.get('AUART') or ''
            
            company_registry = first.get('WERKS') or ''
            if company_registry:
                company_id = company_model.search([
                    ('company_registry', '=', company_registry),
                    ('sync_wms', '=', True),
                ], limit=1)
                if not company_id:
                    _logger.info(f"cron_synchronize_sap_production_order COMPANY: {company_registry} SKIPPED")
                    continue
                
            product_code = (first.get('MATNR') or '').lstrip('0')
            if product_code:
                product_id = product_model.search([('default_code', '=', product_code),('company_id', '=', company_id.id)], limit=1)
                if not product_id:
                    _logger.info(f"cron_synchronize_sap_production_order PRODUCT: {product_code} SKIPPED")
                    continue
            
            unit = first.get('GMEIN') or ''
            product_uom = False
            if unit.upper() != "KG":
                raw_umrez = str(first.get('UMREZ') or '').strip()
                uom_numerator = float(raw_umrez if raw_umrez else 0.0)
                
                raw_umren = str(first.get('UMREN') or '').strip()
                uom_denominator = float(raw_umren if raw_umren else 0.0)
                
                ratio = (uom_numerator / uom_denominator) if uom_denominator else 0.0
                ratio = int(ratio) if ratio.is_integer() else ratio
                uom_name = f"{unit} {ratio}"
                product_uom = uom_model.search([('name', '=', uom_name)], limit=1)
            else:
                product_uom = uom_model.search([('name', '=', 'kg')], limit=1)
            
            start_date = False
            finish_date = False
            raw_start = first.get('GSTRP')
            if raw_start and len(raw_start) == 8:
                start_date = datetime.strptime(raw_start, "%Y%m%d").date()

            raw_finish = first.get('GLTRP')
            if raw_finish and len(raw_finish) == 8:
                finish_date = datetime.strptime(raw_finish, "%Y%m%d").date()
            
            raw_gamng = str(first.get('GAMNG') or '').strip()
            order_qty = float(raw_gamng if raw_gamng else 0.0)
            created_user = first.get('ERNAM') or ''
            teco_status = (first.get('TECO_STATUS') or '').strip().upper()
            loekz = (first.get('LOEKZ') or '').strip()
            
            vals = {
                'po_number': po_number,
                'order_type': order_type,
                'start_date': start_date,
                'finish_date': finish_date,
                'product_id': product_id.id if product_id else False,
                'uom_id': product_uom.id if product_uom else False,
                'order_qty': order_qty,
                'company_id': company_id.id if company_id else False,
                'company_registry': company_id.company_registry if company_id else False,
                'status_teco': teco_status,
                'created_user': created_user,
                'sap_pp': True,
                'active': loekz != 'X',
            }
            
            prod_order = po_sap_model.search([('po_number', '=', po_number)], limit=1)
            if not prod_order:
                prod_order = po_sap_model.create(vals)
                prod_order.message_post(body=f"PO SAP {prod_order.po_number} Created from Cron")
                _logger.info(f"PO SAP {prod_order.po_number} Created")
            else:
                if self._needs_update(prod_order, vals):
                    prod_order.write(vals)
                    _logger.info(f"PO {prod_order.po_number} Updated")
                
                if teco_status == 'TECO':
                    if prod_order.state != 'teco':
                        prod_order.write({'state': 'teco', 'status_teco': 'TECO'})
                else:
                    if prod_order.state != 'teco':
                        prod_order.write({'state': 'in_progress', 'status_teco': 'NOT TECO'})
            
            for row in rows:
                component_code = (row.get('COMPONENT')).lstrip('0')
                component = product_model.search([('default_code', '=', component_code),('company_id', '=', company_id.id)], limit=1)
                if not component:
                    continue
                
                op_type_id = False
                for wip in component.product_wip_line_ids:
                    if wip.product_id.id == component.id:
                        op_type_id = wip.warehouse_id.pick_type_id.id
                        break
                
                uom_component = (row.get('UOM_COMP')).strip().lower()
                uom_comp = uom_model.search([('name', '=', uom_component)], limit=1)
                if not uom_comp:
                    continue
                
                qty_component = float(row.get('BDMNG') or 0)
                seq_component = row.get('RSPOS')
                
                existing_line = po_sap_line_model.search([
                    ('po_sap_id', '=', prod_order.id),
                    ('no_item', '=', seq_component)
                ], limit=1)
                
                vals_line = {
                    'po_sap_id': prod_order.id,
                    'no_item': seq_component,
                    'product_id': component.id,
                    'uom_id': uom_comp.id,
                    'order_qty': qty_component,
                    'picking_type_id': op_type_id,
                }
                
                if existing_line:
                    if self._needs_update(existing_line, vals_line):
                        existing_line.write({
                            'order_qty': qty_component,
                            'uom_id': uom_comp.id, 
                        })
                else:
                    existing_line = po_sap_line_model.create(vals_line)
                
                if existing_line.po_sap_id.state != 'teco' and not existing_line.picking_created:
                    existing_line.action_create_picking_wip()

            _logger.info(f"PROD ORDER {po_number} total line {len(rows)}")
            
        
    def action_picking_po_sap(self):
        operation_type_barcode_fg = self.env['ir.config_parameter'].sudo().get_param('operation_type_barcode_fg')
        operation_type = self.env['stock.picking.type'].sudo().search([('company_id', '=', self.company_id.id),('barcode', '=', str(operation_type_barcode_fg))], limit=1)
        if not operation_type:
            raise ValidationError(f"Operation Type tidak ditemukan untuk Company {self.company_id.company_registry} dan Barcode {operation_type_barcode_fg or ''}")
        right_now = self.now_jakarta()
        now_hour = right_now.strftime('%H%M')
        prod_shift = self.env['production.shift'].sudo().search([('date_start', '<=', now_hour),('date_end', '>=', now_hour),], limit=1)
        uom_kg = self.env['uom.uom'].sudo().search([('name', '=', 'kg')], limit=1)
        
        today = self.today_jakarta()
        last_picking_id = False
        for rec in self:
            if not rec.active:
                raise ValidationError("Tidak bisa melakukan GR FG karena Data Inactive")
            if rec.state == 'teco':
                raise ValidationError("Tidak bisa melakukan GR FG karena State sudah TECO")
            # if rec.finish_date and today > rec.finish_date:
            #     raise ValidationError(f"Tidak bisa melakukan GR WIP karena {today} sudah melebihi Finish Date {rec.finish_date}")
            
            bag_qty = ((rec.remaining_qty * rec.uom_id.factor) / 1000)
            picking = self.env['stock.picking'].sudo().create({
                'picking_type_id': operation_type.id,
                'location_dest_id': operation_type.default_location_dest_id.id,
                'production_shift_id': prod_shift.id or False,
                'scheduled_date': rec.finish_date,
                'date_deadline': rec.finish_date,
                'po_sap_id': rec.id,
                'company_id': rec.company_id.id,
                'origin': rec.po_number,
                'note': f"FG Created From Production Order {rec.po_number}",
            })
            
            move_vals = []
            if picking:
                for wip in rec.product_id.product_wip_line_ids.filtered(lambda x: x.warehouse_id.id == picking.picking_type_id.warehouse_id.id):
                    if wip.product_id == rec.product_id:
                        move_vals.append({
                            'picking_id': picking.id,
                            'product_id': wip.product_id.id,
                            'product_uom_qty': bag_qty if bag_qty > 0 else 1,
                            'product_uom': uom_kg.id if rec.uom_id.name == 'kg' else rec.uom_id.id,
                            'company_id': rec.company_id.id,
                        })    
                
                if move_vals:
                    self.env['stock.move'].sudo().create(move_vals)
                
                picking.message_post(body=f"FG Created From Production Order {rec.po_number}")
                picking.action_confirm()
                last_picking_id = picking.id
                if picking.move_line_ids:
                    picking.move_line_ids.sudo().write({'stock_type': 'QI'})
                rec.sudo().write({'state': 'in_progress'})
        
        if last_picking_id:
            last_picking_record = self.env['stock.picking'].browse(last_picking_id)
            return last_picking_record.action_open_picking_client_action()
            
        return {'type': 'ir.actions.act_window_close'}
    
    def action_picking_wip_po(self):
        operation_type_barcode_wip = self.env['ir.config_parameter'].sudo().get_param('operation_type_barcode_wip')
        operation_type = self.env['stock.picking.type'].sudo().search([('company_id', '=', self.company_id.id), ('barcode', '=', str(operation_type_barcode_wip))], limit=1)
        if not operation_type:
            raise ValidationError(f"Operation Type tidak ditemukan untuk Company {self.company_id.company_registry} dan Barcode {operation_type_barcode_wip or ''}")
        right_now = self.now_jakarta()
        now_hour = right_now.strftime('%H%M')
        prod_shift = self.env['production.shift'].sudo().search([('date_start', '<=', now_hour),('date_end', '>=', now_hour)], limit=1)
        uom_kg = self.env['uom.uom'].sudo().search([('name', '=', 'kg')], limit=1)

        last_picking_id = False
        today = self.today_jakarta()
        for rec in self:
            if not rec.active:
                raise ValidationError("Tidak bisa melakukan GR WIP karena Data Inactive")
            if rec.state == 'teco':
                raise ValidationError("Tidak bisa melakukan GR WIP karena State sudah TECO")
            # if rec.finish_date and today > rec.finish_date:
            #     raise ValidationError(f"Tidak bisa melakukan GR WIP karena {today} sudah melebihi Finish Date {rec.finish_date}")
            
            bag_qty = ((rec.remaining_qty * rec.uom_id.factor) / 1000)
            picking = self.env['stock.picking'].sudo().create({
                'picking_type_id': operation_type.id,
                'location_id': operation_type.default_location_src_id.id,
                'location_dest_id': operation_type.default_location_dest_id.id,
                'production_shift_id': prod_shift.id or False,
                'scheduled_date': rec.finish_date,
                'date_deadline': rec.finish_date,
                'po_sap_id': rec.id,
                'company_id': rec.company_id.id,
                'origin': rec.po_number,
                'note': f"WIP Created From Production Order {rec.po_number}",
            })
            
            move_vals = []
            if picking:
                for wip in rec.product_id.product_wip_line_ids.filtered(lambda x: x.warehouse_id.id == picking.picking_type_id.warehouse_id.id):
                    if wip.product_id == rec.product_id:
                        move_vals.append({
                            'picking_id': picking.id,
                            'product_id': wip.product_id.id,
                            'product_uom_qty': bag_qty if bag_qty > 0 else 1,
                            'product_uom': uom_kg.id if rec.uom_id.name == 'kg' else rec.uom_id.id,
                            'company_id': rec.company_id.id,
                        })   

                if move_vals:
                    self.env['stock.move'].sudo().create(move_vals)
                    
                picking.message_post(body=f"WIP Created From Production Order {rec.po_number}")
                picking.action_confirm()
                last_picking_id = picking.id
                if picking.move_line_ids:
                    picking.move_line_ids.sudo().write({'stock_type': 'QI'})
                rec.sudo().write({'state': 'in_progress'})

        if last_picking_id:
            last_picking_record = self.env['stock.picking'].browse(last_picking_id)
            return last_picking_record.action_open_picking_client_action()
            
        return {'type': 'ir.actions.act_window_close'}
    
    # Isi Product berdasarkan FAMILY SKU    
    # def action_picking_wip_po(self):
    #     operation_type_barcode_wip = self.env['ir.config_parameter'].sudo().get_param('operation_type_barcode_wip')
    #     operation_type = self.env['stock.picking.type'].sudo().search([
    #         ('company_id', '=', self.company_id.id),
    #         ('barcode', '=', str(operation_type_barcode_wip))
    #     ], limit=1)
        
    #     if not operation_type:
    #         raise ValidationError(f"Operation Type tidak ditemukan untuk Company {self.company_id.company_registry} dan move type {operation_type_barcode_wip or ''}")

    #     right_now = self.now_jakarta()
    #     now_hour = right_now.strftime('%H%M')
    #     prod_shift = self.env['production.shift'].sudo().search([
    #         ('date_start', '<=', now_hour),
    #         ('date_end', '>=', now_hour)
    #     ], limit=1)
        
    #     uom_kg = self.env['uom.uom'].sudo().search([('name', '=', 'kg')], limit=1)
    #     if not uom_kg:
    #         raise ValidationError("UoM 'kg' tidak ditemukan di sistem.")

    #     last_picking_id = False
    #     for rec in self:
    #         if not rec.active:
    #             raise ValidationError("Tidak bisa melakukan GR WIP karena Data Inactive")
    #         if rec.state == 'teco':
    #             raise ValidationError("Tidak bisa melakukan GR WIP karena State sudah TECO")
    #         if rec.finish_date:
    #             if fields.Date.today() > rec.finish_date:
    #                 raise ValidationError(f"Tidak bisa melakukan GR WIP karena {fields.Date.today()} sudah melebihi Finish Date {rec.finish_date}")
                
    #         picking = self.env['stock.picking'].sudo().create({
    #             'picking_type_id': operation_type.id,
    #             'location_id': operation_type.default_location_src_id.id,
    #             'location_dest_id': operation_type.default_location_dest_id.id,
    #             'production_shift_id': prod_shift.id or False,
    #             'scheduled_date': rec.finish_date,
    #             'date_deadline': rec.finish_date,
    #             'po_sap_id': rec.id,
    #             'company_id': rec.company_id.id,
    #             'origin': rec.po_number,
    #         })
            
    #         move_vals = []
    #         if picking:
    #             if rec.product_id:
    #                 move_vals.append({
    #                     'picking_id': picking.id,
    #                     'product_id': rec.product_id.id,
    #                     'product_uom_qty': 1,
    #                     'product_uom': rec.uom_id.id,
    #                     'company_id': rec.company_id.id,
    #                     'location_id': operation_type.default_location_src_id.id,
    #                     'location_dest_id': operation_type.default_location_dest_id.id,
    #                 })

    #             for wip in rec.product_id.product_wip_line_ids.filtered(lambda x: x.warehouse_id.id == picking.picking_type_id.warehouse_id.id):
    #                 if wip.product_id:
    #                     move_vals.append({
    #                         'picking_id': picking.id,
    #                         'product_id': wip.product_id.id,
    #                         'product_uom_qty': 1,
    #                         'product_uom': uom_kg.id,
    #                         'company_id': rec.company_id.id,
    #                         'location_id': operation_type.default_location_src_id.id,
    #                         'location_dest_id': operation_type.default_location_dest_id.id,
    #                     })
                
    #             if move_vals:
    #                 self.env['stock.move'].sudo().create(move_vals)
                    
    #             picking.message_post(body=f"Created From Production Order {rec.po_number}")
    #             picking.action_confirm()
    #             last_picking_id = picking.id
    #             if picking.move_line_ids:
    #                 picking.move_line_ids.sudo().write({'stock_type': 'QI'})
    #             rec.sudo().write({'state': 'in_progress'})

    #     if last_picking_id:
    #         last_picking_record = self.env['stock.picking'].browse(last_picking_id)
    #         return last_picking_record.action_open_picking_client_action()
            
    #     return {'type': 'ir.actions.act_window_close'}