from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import datetime
from collections import defaultdict
import requests
import json
import logging
import re
import pytz
_logger = logging.getLogger(__name__)


class InheritSaleOrderSAP(models.Model):
    _inherit = 'sale.order'
    
    is_sap = fields.Boolean(string="SAP", default=False, tracking=True)
    so_sap = fields.Char(string="SO SAP", tracking=True)
    do_sap = fields.Char(string="DO SAP", tracking=True)
    po_sap = fields.Char(string="PO SAP", tracking=True)
    sales_sap_name = fields.Char(string="Sales Name", tracking=True)
    nomor_polisi_desc = fields.Text(string="Nomor Polisi", tracking=True)
    date_order_sap = fields.Date(string="Date Order", tracking=True)
    so_sto = fields.Boolean(string="STO", default=False)
    sloc_to_sloc = fields.Boolean(string="Sloc to Sloc", default=False)
    sloc_to = fields.Char(string="SLOC To", readonly=True)

    def now_jakarta(self):
        tz = pytz.timezone('Asia/Jakarta')
        now_jakarta = datetime.now(tz)
        return now_jakarta
    
    @api.depends('name', 'do_sap')
    def _compute_display_name(self):
        for rec in self:
            so_name = rec.name if rec.name else "(Empty)"
            do_sap = rec.do_sap if rec.do_sap else "-"
            name = '%s - [%s]' % (so_name, do_sap)
            rec.display_name = name
    
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
    
    @api.model
    def cron_synchronize_sap_sale_order(self):
        data_list = self._fetch_sap_data(
            config_key='query_sale_order_sap',
            cron_name='cron_synchronize_sap_sale_order',
        )
        if not data_list:
            return True

        _logger.info(f"TOTAL DATA cron_synchronize_sap_sale_order {len(data_list)}")

        sale_order_model = self.env['sale.order'].sudo()
        sale_order_line_model = self.env['sale.order.line'].sudo()
        partner_model = self.env['res.partner'].sudo()
        company_model = self.env['res.company'].sudo()
        product_model = self.env['product.product'].sudo()
        uom_model = self.env['uom.uom'].sudo()
        delivery_carrier_model = self.env['delivery.carrier'].sudo()
        warehouse_model = self.env['stock.warehouse'].sudo()

        grouped_data = defaultdict(list)

        for row in data_list:
            nomor_do = row.get('NOMOR_DO')
            if nomor_do:
                grouped_data[nomor_do].append(row)
        for nomor_do, rows in grouped_data.items():
            first = rows[0]
            nomor_so = first.get('SALES_ORDER_NO')
            customer_ref = first.get('SOLD_TO_CODE')
            delivery_ref = first.get('SHIP_TO_CODE')
            erdat = first.get('ERDAT')
            company_registry = first.get('WERKS')
            ernam = first.get('ERNAM')
            delivery_method = (first.get('DELIVERY_METHOD') or '').strip().upper()
            stock_warehouse = first.get('LGORT')
            trucknr = first.get('TRUCKNR')
            ktokd = (first.get('KTOKD') or '').strip().upper()

            partner = partner_model.search([('ref', '=', customer_ref)], limit=1)
            if not partner:
                _logger.info(f"cron_synchronize_sap_sale_order PARTNER {customer_ref} SKIPPED")
                continue

            partner_shipping = partner_model.search([('ref', '=', delivery_ref)], limit=1)
            if not partner_shipping:
                _logger.info(f"cron_synchronize_sap_sale_order DELIVERY REF {delivery_ref} SKIPPED")
                continue

            company = company_model.search([('company_registry', '=', company_registry),('sync_wms', '=', True)], limit=1)
            if not company:
                _logger.info(f"cron_synchronize_sap_sale_order Company {company_registry} SKIPPED")
                continue
            
            warehouse = warehouse_model.search([('lot_stock_id.sloc_id.code', '=', stock_warehouse),('company_id', '=', company.id)], limit=1)
            if not warehouse:
                _logger.info(f"cron_synchronize_sap_sale_order Warehouse {stock_warehouse} SKIPPED")
                continue

            order_date = False
            if erdat and len(erdat) == 8:
                order_date = datetime.strptime(erdat, "%Y%m%d")
                
            deliv_method = ""
            if delivery_method == "LOC":
                if ktokd == 'ZN01' or ktokd == 'ZI01':
                    deliv_method = "SO LOCO 909"
                if ktokd == 'ZR01':
                    deliv_method = "SO LOCO 905"
            if delivery_method == "FRC":
                deliv_method = "SO FRANCO"
            
            deliv_carrier = delivery_carrier_model.search([('name', 'ilike', deliv_method),('company_id', '=', company.id)], limit=1)
            if not deliv_carrier:
                _logger.info(f"cron_synchronize_sap_sale_order Delivery Carrier {deliv_method} SKIPPED")

            so = sale_order_model.search([('do_sap', '=', nomor_do),('company_id', '=', company.id)], limit=1)
            vals = {
                'is_sap': True,
                'do_sap': nomor_do,
                'so_sap': nomor_so,
                'partner_id': partner.id,
                'partner_shipping_id': partner_shipping.id,
                'date_order': order_date,
                'date_order_sap': order_date,
                'carrier_id': deliv_carrier.id,
                'sales_sap_name': ernam,
                'company_id': company.id,
                'warehouse_id': warehouse.id,
                'nomor_polisi_desc': trucknr,
            }
            if not so:
                so = sale_order_model.create(vals)
                so.message_post(body=f"SO SAP {nomor_do} Created from Cron")
                so.action_confirm()
                _logger.info(f"SO Created {nomor_do}")
            else:
                if self._needs_update(so, vals):
                    so.write(vals)

            for row in rows:
                product_code = (row.get('MATNR')).lstrip('0')
                product = product_model.search([('default_code', '=', product_code),('company_id', '=', company.id)], limit=1)
                if not product:
                    continue

                delivery_uom = row.get('DELIVERY_UOM')
                uom_numerator = float(row.get('UOM_NUMERATOR') or 1)
                uom_denominator = float(row.get('UOM_DENOMINATOR') or 1)
                product_uom = product.uom_bag_id
                if delivery_uom and delivery_uom.upper() != "KG":
                    ratio = float(uom_numerator) / float(uom_denominator)
                    ratio = int(ratio) if ratio.is_integer() else ratio
                    uom_name = f"{delivery_uom} {ratio}"
                    uom = uom_model.search([('name', '=', uom_name)], limit=1)
                    if uom:
                        product_uom = uom

                qty = float(row.get('DELIVERY_QTY') or 0)
                posnr = (row.get('POSNR') or "").lstrip('0')
                existing_line = sale_order_line_model.search([
                    ('order_id', '=', so.id),
                    ('product_id', '=', product.id),
                    ('sap_sequence', '=', posnr)
                ], limit=1)

                vals_line = {
                    'order_id': so.id,
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'product_uom_id': product_uom.id,
                    'sap_sequence': posnr,
                    'order_seq': posnr,
                }

                if existing_line:
                    if self._needs_update(existing_line, vals_line):
                        existing_line.write({
                            'product_uom_qty': qty,
                            'product_uom_id': product_uom.id,
                        })
                else:
                    sale_order_line_model.create(vals_line)

            _logger.info(f"SO {nomor_do} total line {len(rows)}")
            
                
    @api.model
    def cron_synhronize_sap_so_sto(self):
        data_list = self._fetch_sap_data(
            config_key='query_so_sto_sap',
            cron_name='cron_synhronize_sap_so_sto',
        )
        if not data_list:
            return True

        _logger.info(f"TOTAL DATA cron_synhronize_sap_so_sto {len(data_list)}")
        
        so_model = self.env['sale.order'].sudo()
        so_line_model = self.env['sale.order.line'].sudo()
        partner_model = self.env['res.partner'].sudo()
        company_model = self.env['res.company'].sudo()
        product_model = self.env['product.product'].sudo()
        uom_model = self.env['uom.uom'].sudo()
        warehouse_model = self.env['stock.warehouse'].sudo()
        delivery_carrier_model = self.env['delivery.carrier'].sudo()
        
        grouped_data = defaultdict(list)
        
        for row in data_list:
            nomor_do = row.get('VBELN_VL')
            if nomor_do:
                grouped_data[nomor_do].append(row)
        
        for nomor_do, rows in grouped_data.items():
            first = rows[0]
            date_order_sap = first.get('ARRDATE')
            nomor_polisi_desc = first.get('TRUCKNR')
            company_registry = first.get('WERKS')
            stock_warehouse = first.get('LGORT')
            partner = first.get('KUNNR') or first.get('SHIP_TO')
            sales_name = first.get('ERNAM')
            po_sap = first.get('EBELN')
            
            partner = partner_model.search([('ref', '=', partner)], limit=1)
            if not partner:
                _logger.info(f"cron_synhronize_sap_so_sto partner {partner} skipped")
                continue
            
            company = company_model.search([('company_registry', '=', company_registry),('sync_wms', '=', True)], limit=1)
            if not company:
                _logger.info(f"cron_synhronize_sap_so_sto company_registry {company_registry} skipped")
                continue
            
            warehouse = warehouse_model.search([
                ('lot_stock_id.sloc_id.code', '=', stock_warehouse),
                ('company_id', '=', company.id),
            ], limit=1)
            if not warehouse:
                _logger.info(f"cron_synhronize_sap_so_sto warehouse sloc code {stock_warehouse} skipped")
                continue
            
            date_order = False
            if date_order_sap and len(date_order_sap) == 8:
                date_order = datetime.strptime(date_order_sap, "%Y%m%d")
                
            deliv_carrier = delivery_carrier_model.search([('name', 'ilike', "STO Plant to Plant"),('company_id', '=', company.id)], limit=1)
            
            so = so_model.search([
                ('do_sap', '=', nomor_do),
                ('company_id', '=', company.id),
                ('so_sto', '=', True)
            ], limit=1)
            vals = {
                'is_sap': True,
                'so_sto': True,
                'do_sap': nomor_do,
                'partner_id': partner.id,
                'warehouse_id': warehouse.id,
                'date_order': date_order,
                'date_order_sap': date_order,
                'sales_sap_name': sales_name,
                'nomor_polisi_desc': nomor_polisi_desc,
                'carrier_id': deliv_carrier.id if deliv_carrier else False,
                'company_id': company.id,
                'po_sap': po_sap,
            }
            if not so:
                so = so_model.create(vals)
                so.message_post(body=f"SO SAP {nomor_do} Created from Cron")
                _logger.info(f"SO Created {nomor_do}")
                so.action_confirm()
            else:
                if self._needs_update(so, vals):
                    so.write(vals)
            
            for row in rows:
                product_code = (row.get('MATNR') or '').lstrip('0')
                product = product_model.search([('default_code', '=', product_code),('company_id', '=', company.id)], limit=1)
                if not product:
                    _logger.info(f"cron_synhronize_sap_so_sto product {product_code} skipped")
                    continue
                
                delivery_uom = row.get('VRKME')
                uom_numerator = float(row.get('UMREZ'))
                uom_denominator = float(row.get('UMREN'))
                product_uom = product.uom_bag_id
                if delivery_uom and delivery_uom.upper() != "KG":
                    ratio = float(uom_numerator) / float(uom_denominator)
                    ratio = int(ratio) if ratio.is_integer() else ratio
                    uom_name = f"{delivery_uom} {ratio}"
                    uom = uom_model.search([('name', '=', uom_name)], limit=1)
                    if uom:
                        product_uom = uom
                
                qty = float(row.get('LFIMG') or 0)
                posnr = (row.get('POSNR') or "").lstrip('0')
                po_seq = (row.get('VGPOS') or "").lstrip('0')
                existing_line = so_line_model.search([
                    ('order_id', '=', so.id),
                    ('product_id', '=', product.id),
                    ('sap_sequence', '=', posnr),
                ], limit=1)
                vals_line = {
                    'order_id': so.id,
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'product_uom_id': product_uom.id,
                    'sap_sequence': posnr,
                    'order_seq': po_seq,
                }
                
                if not existing_line:
                    so_line_model.create(vals_line)
                else:
                    if self._needs_update(existing_line, vals_line):
                        existing_line.write({
                            'product_uom_qty': qty,
                            'product_uom_id': product_uom.id,
                        })
        # sekalian jalanin sloc to sloc
        self.cron_synhronize_so_sloc_to_sloc()
      
    @api.model
    def _process_auto_done_picking(self, config_key, search_field, data_key, cron_name):
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
        url = f"{ip_sap_rfc}/api/v1/zfm-query-data"
        body = {
            "I_QUERY": str(query),
            "I_MOD": f"CRON {cron_name}"
        }

        try:
            response = requests.post(url=url, headers=headers, data=json.dumps(body))
        except Exception as e:
            raise ValidationError(str(e))

        res = response.json()
        if res.get('error'):
            raise ValidationError(json.dumps(res.get('error')))
        if not res.get('success'):
            _logger.info(f"CRON {cron_name} NOT SUCCESS")
            return

        data_list = res.get('data', [])
        if not data_list:
            return

        _logger.info(f"TOTAL DATA {cron_name}: {len(data_list)}")

        pick_delivery_model = self.env['stock.picking'].sudo()
        for data in data_list:
            if not data.get('MBLNR'):
                continue

            value = data.get(data_key)
            picking = pick_delivery_model.search([
                (search_field, '=', value),
                ('picking_type_id.code', '=', 'outgoing'),
                ('state', '=', 'assigned'),
            ], limit=1)
            if picking:
                picking.button_validate()


    @api.model
    def cron_auto_done_all(self):
        jobs = [
            {
                'config_key': 'query_auto_done_sale_order_do_sap',
                'search_field': 'sale_id.do_sap',
                'data_key': 'LE_VBELN',
                'cron_name': 'cron_auto_done_sale_order_do',
            },
            {
                'config_key': 'query_done_so_plan_to_plan_sap',
                'search_field': 'sale_id.do_sap',
                'data_key': 'EBELN',
                'cron_name': 'cron_auto_done_so_plan_to_plan',
            },
            {
                'config_key': 'query_done_so_sloc_to_sloc_sap',
                'search_field': 'sale_id.po_sap',
                'data_key': 'EBELN',
                'cron_name': 'cron_auto_done_so_sloc_to_sloc',
            },
        ]
        for job in jobs:
            try:
                self._process_auto_done_picking(**job)
            except Exception as e:
                _logger.error(f"Error pada {job['cron_name']}: {e}")
                continue
                            
    @api.model
    def cron_auto_done_sale_order_do(self):
        data_list = self._fetch_sap_data(
            config_key='query_auto_done_sale_order_do_sap',
            cron_name='cron_auto_done_sale_order_do',
        )
        if not data_list:
            return True

        _logger.info(f"TOTAL DATA cron_auto_done_sale_order_do {len(data_list)}")
        
        pick_delivery_model = self.env['stock.picking'].sudo()
        for data in data_list:
            mblnr = data.get('MBLNR')
            if not mblnr:
                continue
            
            nomor_do = data.get('LE_VBELN')
            picking = pick_delivery_model.search([
                ('sale_id.do_sap', '=', nomor_do),
                ('picking_type_id.code', '=', 'outgoing'),
                ('state', '=', 'assigned'),
            ], limit=1)
            if picking:
                picking.button_validate()
                
    @api.model
    def cron_auto_done_git(self):
        icp = self.env['ir.config_parameter'].sudo()
        picking_type_git = icp.get_param('picking_type_git')
        if not picking_type_git:
            raise ValidationError("picking_type_git belum disetting!")

        data_list = self._fetch_sap_data(
            config_key='query_auto_done_git_sap',
            cron_name='cron_auto_done_git',
        )
        if not data_list:
            return True

        pick_delivery_model = self.env['stock.picking'].sudo()
        for data in data_list:
            if not data.get('MBLNR'):
                continue

            nomor_do = data.get('VBELN')
            picking = pick_delivery_model.search([
                ('sale_id.do_sap', '=', nomor_do),
                ('picking_type_id.move_type_sap', '=', str(picking_type_git)),
                ('state', '=', 'assigned'),
            ], limit=1)
            if picking:
                picking.button_validate()
                
                
    @api.model
    def cron_synhronize_so_sloc_to_sloc(self):
        data_list = self._fetch_sap_data(
            config_key='query_so_sloc_to_sloc_sap',
            cron_name='cron_synhronize_so_sloc_to_sloc',
        )
        if not data_list:
            return True
        _logger.info(f"TOTAL DATA cron_synhronize_so_sloc_to_sloc: {len(data_list)}")
        
        so_model = self.env['sale.order'].sudo()
        so_line_model = self.env['sale.order.line'].sudo()
        partner_model = self.env['res.partner'].sudo()
        company_model = self.env['res.company'].sudo()
        product_model = self.env['product.product'].sudo()
        uom_model = self.env['uom.uom'].sudo()
        location_model = self.env['stock.location'].sudo()
        delivery_carrier_model = self.env['delivery.carrier'].sudo()
        
        grouped_data = defaultdict(list)
        
        for row in data_list:
            po_sap = row.get('EBELN')
            if po_sap:
                grouped_data[po_sap].append(row)
        
        for po_sap, rows in grouped_data.items():
            first = rows[0]
            date_order_sap = first.get('ARRDATE')
            nomor_polisi_desc = first.get('TRUCKNR')
            company_registry = first.get('WERKS')
            stock_warehouse = first.get('SLOC')
            partner = first.get('KUNNR') or first.get('SHIP_TO')
            sales_name = first.get('ERNAM')
            ke_sloc = first.get('KESLOC')
            nomor_do = first.get('VBELN_VL')
            
            partner = partner_model.search([('ref', '=', company_registry)], limit=1)
            if not partner:
                _logger.info(f"cron_synhronize_so_sloc_to_sloc Partner {partner} skipped")
                continue
            
            company = company_model.search([('company_registry', '=', company_registry),('sync_wms', '=', True)], limit=1)
            if not company:
                _logger.info(f"cron_synhronize_so_sloc_to_sloc Company {company_registry} skipped")
                continue
            
            warehouse = location_model.search([
                ('sloc_id.code', '=', stock_warehouse),
                ('location_id.usage', '=', 'view'),
                ('company_id', '=', company.id)
            ], limit=1)
            if not warehouse:
                _logger.info(f"cron_synhronize_so_sloc_to_sloc Warehouse Sloc Code {stock_warehouse} skipped")
                continue
            
            date_order = False
            if date_order_sap and len(date_order_sap) == 8:
                date_order = datetime.strptime(date_order_sap, "%Y%m%d")
                
            deliv_carrier = delivery_carrier_model.search([('name', 'ilike', "STO Sloc to Sloc"),('company_id', '=', company.id)], limit=1)
            
            so = so_model.search([
                ('po_sap', '=', po_sap),
                ('company_id', '=', company.id),
                ('sloc_to_sloc', '=', True)
            ], limit=1)
            vals = {
                'is_sap': True,
                'so_sto': True,
                'sloc_to_sloc': True,
                'po_sap': po_sap,
                'do_sap': nomor_do,
                'sloc_to': ke_sloc,
                'partner_id': partner.id,
                'warehouse_id': warehouse.warehouse_id.id,
                'date_order': date_order,
                'date_order_sap': date_order,
                'sales_sap_name': sales_name,
                'nomor_polisi_desc': nomor_polisi_desc,
                'carrier_id': deliv_carrier.id if deliv_carrier else False,
                'company_id': company.id,
            }
            if not so:
                so = so_model.create(vals)
                so.message_post(body=f"SO SAP {po_sap} Created from Cron")
                _logger.info(f"SO Created {po_sap}")
                so.action_confirm()
            else:
                if self._needs_update(so, vals):
                    so.write(vals)
            
            for row in rows:
                product_code = (row.get('MATNR') or "").lstrip('0')
                product = product_model.search([
                    ('default_code', '=', product_code),
                    ('company_id', '=', company.id)
                ], limit=1)
                if not product:
                    _logger.info(f"SLOC to SLOC Product {product_code} skipped: Not found in master data")
                    continue
                
                delivery_uom = row.get('UOE') or ""
                product_uom = product.uom_bag_id
                if delivery_uom:
                    if delivery_uom[-1].isdigit():
                        uom_name = delivery_uom
                        uom = uom_model.search([('name', '=', uom_name)], limit=1)
                        if uom:
                            product_uom = uom
                    else:
                        uom_numerator = float(row.get('UMREZ') or 0)
                        uom_denominator = float(row.get('UMREN') or 1)
                        if delivery_uom.upper() != "KG" and uom_denominator != 0:
                            ratio = float(uom_numerator) / float(uom_denominator)
                            ratio = int(ratio) if ratio.is_integer() else ratio
                            uom_name = f"{delivery_uom} {ratio}"
                            
                            uom = uom_model.search([('name', '=', uom_name)], limit=1)
                            if uom:
                                product_uom = uom
                
                qty = float(row.get('QTYPO') or 0.0)
                posnr = (row.get('POSNR') or "").lstrip('0')
                po_seq = (row.get('EBELP') or "").lstrip('0')
                
                existing_line = so_line_model.search([
                    ('order_id', '=', so.id),
                    ('product_id', '=', product.id),
                    ('sap_sequence', '=', posnr),
                ], limit=1)
                
                product_uom_id = product_uom.id if product_uom else False
                
                vals_line = {
                    'order_id': so.id,
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'product_uom_id': product_uom_id, 
                    'sap_sequence': posnr,
                    'order_seq': po_seq,
                }
                
                if not existing_line:
                    so_line_model.create(vals_line)
                else:
                    if hasattr(self, '_needs_update') and self._needs_update(existing_line, vals_line):
                        existing_line.write({
                            'product_uom_qty': qty,
                            'product_uom_id': product_uom_id,
                        })
                        
    @api.model
    def _run_query_update_sap(
        self, *,
        cron_name,
        query_param_key,
        field_name,
        format_key,
        model_name='sale.order',
        sync_field='is_sap',
        state_value='sale',
        domain_extra=None,
    ):
        icp = self.env['ir.config_parameter'].sudo()
        x_i_api_key = icp.get_param('x_i_api_key')
        ip_sap_rfc = icp.get_param('ip_sap_rfc')
        query_template = icp.get_param(query_param_key)

        for param_name, value in [
            ('x_i_api_key', x_i_api_key),
            ('ip_sap_rfc', ip_sap_rfc),
            (query_param_key, query_template),
        ]:
            if not value:
                raise ValidationError(f"{param_name} belum disetting!")

        domain = [
            (field_name, '!=', False),
            (sync_field, '=', True),
            ('state', '=', state_value),
        ] + (domain_extra or [])

        records = self.env[model_name].sudo().search(domain)
        value_list = [
            (getattr(rec, field_name) or '').strip().replace("'", "''")
            for rec in records
            if getattr(rec, field_name)
        ]

        if not value_list:
            _logger.info(f"{cron_name}: list {field_name} kosong, skipped!")
            return True

        values_str = ",".join(f"'{v}'" for v in set(value_list))
        query = query_template.format(**{format_key: values_str})

        headers = {
            "x-i-api-key": str(x_i_api_key),
            "Content-Type": "application/json",
        }
        body = {
            "I_QUERY": query,
            "I_MOD": f"CRON {cron_name}",
        }

        try:
            response = requests.post(
                url=f"{ip_sap_rfc}/api/v1/zfm-query-data",
                headers=headers,
                data=json.dumps(body),
                timeout=120,
            )
        except Exception as e:
            raise ValidationError(str(e))

        if response.status_code != 200:
            raise ValidationError(f"{response.status_code} | {response.text}")

        res = response.json()
        if res.get('error'):
            raise ValidationError(json.dumps(res['error']))
        if not res.get('success'):
            _logger.info(f"{cron_name}: response not success")
            return True

        _logger.info(f"{cron_name}: {len(value_list)} record(s) updated")
        return True

    @api.model
    def cron_synchronize_sap_flag_do_sap(self):
        return self._run_query_update_sap(
            cron_name='cron_synchronize_sap_flag_do_sap',
            query_param_key='query_update_flag_do_sap',
            field_name='do_sap',
            format_key='vbeln',
        )

    @api.model
    def cron_update_zmm_ts_sto_ncd_sap(self):
        return self._run_query_update_sap(
            cron_name='cron_update_zmm_ts_sto_ncd_sap',
            query_param_key='query_update_so_zmm_ts_sto_ncd_sap',
            field_name='po_sap',
            format_key='po_sap',
        )

    @api.model
    def cron_update_zmm_ts_sl_bgd_sap(self):
        return self._run_query_update_sap(
            cron_name='cron_update_zmm_ts_sl_bgd_sap',
            query_param_key='query_update_so_zmm_ts_sl_bgd_sap',
            field_name='do_sap',
            format_key='do_sap',
        )
        
    @api.model
    def cron_update_zmm_ts_sto(self):
        return self._run_query_update_sap(
            cron_name='cron_update_zmm_ts_sto',
            query_param_key='query_update_zmm_ts_sto_sap',
            field_name='do_sap',
            format_key='do_sap',
        )

    @api.model
    def cron_update_update_zmm_ts_sto_ncd_sap(self):
        return self._run_query_update_sap(
            cron_name='cron_update_update_zmm_ts_sto_ncd_sap',
            query_param_key='query_update_zmm_ts_sto_ncd_sap',
            field_name='po_sto',
            format_key='po_sto',
            model_name='purchase.order',
            sync_field='sap_synchronize',
            state_value='purchase',
        )

    @api.model
    def cron_update_update_zmm_ts_in_po_sap(self):
        return self._run_query_update_sap(
            cron_name='cron_update_update_zmm_ts_in_po_sap',
            query_param_key='query_update_zmm_ts_in_po_sap',
            field_name='partner_ref',
            format_key='partner_ref',
            model_name='purchase.order',
            sync_field='sap_synchronize',
            state_value='purchase',
        )
    
    @api.model
    def cron_run_all_query_update(self):
        crons = [
            # sale.order
            self.cron_synchronize_sap_flag_do_sap,
            self.cron_update_zmm_ts_sto_ncd_sap,
            self.cron_update_zmm_ts_sl_bgd_sap,
            self.cron_update_zmm_ts_sto,
            # purchase.order
            self.cron_update_update_zmm_ts_sto_ncd_sap,
            self.cron_update_update_zmm_ts_in_po_sap,
        ]
        for cron in crons:
            try:
                cron()
            except Exception as e:
                _logger.error(f"cron_run_all_query_update: {cron.__name__} FAILED — {e}")
        
        return True
    
    @api.model
    def cron_update_do_sap(self):
        data_list = self._fetch_sap_data(
            config_key='query_update_do_sap',
            cron_name='cron_update_do_sap',
        )
        if not data_list:
            return True
        _logger.info(f"TOTAL DATA cron_update_do_sap: {len(data_list)}")
        
        so_model = self.env['sale.order'].sudo()
        
        for data in data_list:
            vbelv = data.get('VBELV').strip()
            vbeln = data.get('VBELN').strip()
            
            need_update = so_model.search([('so_sap', '=', vbelv)], limit=1)
            if need_update:
                if need_update.do_sap != vbeln:
                    need_update.write({'do_sap': vbeln})
                    need_update.message_post(body=f"DO SAP Updated from cron_update_do_sap")