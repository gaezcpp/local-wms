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
    
    def _needs_update(self, so, vals):
        for field, new_val in vals.items():
            if field not in so._fields:
                continue

            field_def = so._fields[field]
            old_val = so[field]

            if field_def.type == 'many2one':
                old_id = old_val.id if old_val else False
                if old_id != new_val:
                    return True
            else:
                if (old_val or False) != (new_val or False):
                    return True
        return False
    
    @api.model
    def cron_synchronize_sap_sale_order(self):
        icp = self.env['ir.config_parameter'].sudo()
        x_i_api_key = icp.get_param('x_i_api_key')
        ip_sap_rfc = icp.get_param('ip_sap_rfc')
        query_sale_order_sap = icp.get_param('query_sale_order_sap')

        if not x_i_api_key:
            raise ValidationError("x_i_api_key belum disetting!")
        if not ip_sap_rfc:
            raise ValidationError("ip_sap_rfc belum disetting!")
        if not query_sale_order_sap:
            raise ValidationError("query_sale_order_sap belum disetting!")

        headers = {
            "x-i-api-key": str(x_i_api_key),
            "Content-Type": "application/json"
        }

        url = f"{ip_sap_rfc}/api/v1/zfm-query-data"

        body = {
            "I_QUERY": str(query_sale_order_sap),
            "I_MOD": "CRON cron_synchronize_sap_sale_order"
        }

        try:
            response = requests.post(url=url, headers=headers, data=json.dumps(body))
        except Exception as e:
            raise ValidationError(str(e))

        res = response.json()

        if res.get('error'):
            raise ValidationError(json.dumps(res.get('error')))

        if not res.get('success'):
            _logger.info("CRON cron_synchronize_sap_sale_order NOT SUCCESS")
            return True

        data_list = res.get('data', [])

        if not data_list:
            return True

        _logger.info(f"TOTAL DATA SAP {len(data_list)}")

        sale_order_model = self.env['sale.order'].sudo()
        sale_order_line_model = self.env['sale.order.line'].sudo()
        partner_model = self.env['res.partner'].sudo()
        company_model = self.env['res.company'].sudo()
        product_model = self.env['product.product'].sudo()
        uom_model = self.env['uom.uom'].sudo()
        delivery_carrier_model = self.env['delivery.carrier'].sudo()
        location_model = self.env['stock.location'].sudo()

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
            delivery_method = first.get('DELIVERY_METHOD')
            stock_warehouse = first.get('LGORT')

            partner = partner_model.search([('ref', '=', customer_ref)], limit=1)
            if not partner:
                continue

            partner_shipping = partner_model.search([('ref', '=', delivery_ref)], limit=1)
            if not partner_shipping:
                continue
            

            company = company_model.search([
                ('company_registry', '=', company_registry),
                ('sync_wms', '=', True),
            ], limit=1)
            if not company:
                _logger.info(f"CRON SALE ORDER Company {company_registry} SKIPPED")
                continue
            
            warehouse = location_model.search([
                ('sloc_id.code', '=', stock_warehouse),
                ('location_id.usage', '=', 'view'),
                ('company_id', '=', company.id),
            ], limit=1)
            if not warehouse:
                _logger.info(f"CRON SALE ORDER Warehouse {stock_warehouse} SKIPPED")
                continue

            order_date = False
            if erdat and len(erdat) == 8:
                order_date = datetime.strptime(erdat, "%Y%m%d")
                
            deliv_method = "Loco"
            if delivery_method == "FRC":
                deliv_method = "Franco"
            deliv_carrier = delivery_carrier_model.search([('name', '=', deliv_method),('company_id', '=', company.id)], limit=1)

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
                'warehouse_id': warehouse.warehouse_id.id,
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
                product_code = row.get('MATNR')
                if not product_code:
                    continue
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
            
        self.cron_auto_done_sale_order_do()
            
    @api.model
    def cron_update_nopol_sap_sale_order(self):
        icp = self.env['ir.config_parameter'].sudo()
        x_i_api_key = icp.get_param('x_i_api_key')
        ip_sap_rfc = icp.get_param('ip_sap_rfc')

        if not x_i_api_key:
            raise ValidationError("x_i_api_key belum disetting!")
        if not ip_sap_rfc:
            raise ValidationError("ip_sap_rfc belum disetting!")

        headers = {
            "x-i-api-key": str(x_i_api_key),
            "Content-Type": "application/json"
        }

        url = f"{ip_sap_rfc}/api/v1/zfm-query-data"

        sale_orders = self.env['sale.order'].sudo().search([
            ('is_sap', '=', True),
            ('do_sap', '!=', False),
            ('state', 'not in', ('draft', 'cancel'))
        ])

        for so in sale_orders:
            body = {
                "I_QUERY": f"[READ_TEXT]:Z005-EN-{so.do_sap}-VBBK",
                "I_MOD": "CRON cron_update_nopol_sap_sale_order"
            }

            try:
                response = requests.post(url=url, headers=headers, data=json.dumps(body))
            except Exception as e:
                _logger.error(f"SAP Request Error DO {so.do_sap}: {e}")
                continue

            res = response.json()

            if res.get('error'):
                _logger.error(f"SAP Error DO {so.do_sap}: {res.get('error')}")
                continue

            if not res.get('success'):
                _logger.info(f"CRON cron_update_nopol_sap_sale_order NOT SUCCESS DO {so.do_sap}")
                continue

            data = res.get('data', [])

            if not data:
                continue

            nopol_lines = []
            for row in data:
                tdline = row.get('TDLINE')
                if tdline:
                    nopol_lines.append(tdline.strip())

            if not nopol_lines:
                continue

            nomor_polisi_desc = "\n".join(nopol_lines)
            if so.nomor_polisi_desc != nomor_polisi_desc:
                so.write({'nomor_polisi_desc': nomor_polisi_desc})
                _logger.info(f"Nopol updated DO {so.do_sap}")
                
    @api.model
    def cron_synhronize_sap_so_sto(self):
        icp = self.env['ir.config_parameter'].sudo()
        x_i_api_key = icp.get_param('x_i_api_key')
        ip_sap_rfc = icp.get_param('ip_sap_rfc')
        query_so_sto_sap = icp.get_param('query_so_sto_sap')

        if not x_i_api_key:
            raise ValidationError("x_i_api_key belum disetting!")
        if not ip_sap_rfc:
            raise ValidationError("ip_sap_rfc belum disetting!")
        if not query_so_sto_sap:
            raise ValidationError("query_so_sto_sap belum disetting!")

        headers = {
            "x-i-api-key": str(x_i_api_key),
            "Content-Type": "application/json"
        }
        url = f"{ip_sap_rfc}/api/v1/zfm-query-data"
        body = {
            "I_QUERY": str(query_so_sto_sap),
            "I_MOD": "CRON cron_synhronize_sap_so_sto"
        }

        try:
            response = requests.post(url=url, headers=headers, data=json.dumps(body))
        except Exception as e:
            raise ValidationError(str(e))

        res = response.json()

        if res.get('error'):
            raise ValidationError(json.dumps(res.get('error')))

        if not res.get('success'):
            _logger.info("CRON cron_synchronize_sap_sale_order NOT SUCCESS")
            return True

        data_list = res.get('data', [])
        _logger.info(f"TOTAL DATA SAP {len(data_list)}")

        if not data_list:
            return True
        
        so_model = self.env['sale.order'].sudo()
        so_line_model = self.env['sale.order.line'].sudo()
        partner_model = self.env['res.partner'].sudo()
        company_model = self.env['res.company'].sudo()
        product_model = self.env['product.product'].sudo()
        uom_model = self.env['uom.uom'].sudo()
        location_model = self.env['stock.location'].sudo()
        
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
                continue
            
            company = company_model.search([('company_registry', '=', company_registry),('sync_wms', '=', True)], limit=1)
            if not company:
                continue
            
            warehouse = location_model.search([
                ('sloc_id.code', '=', stock_warehouse),
                ('location_id.usage', '=', 'view'),
                ('company_id', '=', company.id)
            ], limit=1)
            if not warehouse:
                continue
            
            print(f"XXXXXXXXXXXXXXXXXXX {warehouse}")
            
            date_order = False
            if date_order_sap and len(date_order_sap) == 8:
                date_order = datetime.strptime(date_order_sap, "%Y%m%d")
            
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
                'warehouse_id': warehouse.warehouse_id.id,
                'date_order': date_order,
                'date_order_sap': date_order,
                'sales_sap_name': sales_name,
                'nomor_polisi_desc': nomor_polisi_desc,
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
                product_code = row.get('MATNR')
                if not product_code:
                    continue
                product = product_model.search([('default_code', '=', product_code),('company_id', '=', company.id)], limit=1)
                if not product:
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
                        
    @api.model
    def cron_auto_done_sale_order_do(self):
        icp = self.env['ir.config_parameter'].sudo()
        x_i_api_key = icp.get_param('x_i_api_key')
        ip_sap_rfc = icp.get_param('ip_sap_rfc')
        query_auto_done_sale_order_do = icp.get_param('query_auto_done_sale_order_do')
        if not x_i_api_key:
            raise ValidationError("x_i_api_key belum disetting!")
        if not ip_sap_rfc:
            raise ValidationError("ip_sap_rfc belum disetting!")
        if not query_auto_done_sale_order_do:
            raise ValidationError("query_auto_done_sale_order_do belum disetting!")

        headers = {
            "x-i-api-key": str(x_i_api_key),
            "Content-Type": "application/json"
        }
        url = f"{ip_sap_rfc}/api/v1/zfm-query-data"
        body = {
            "I_QUERY": str(query_auto_done_sale_order_do),
            "I_MOD": "CRON cron_auto_done_sale_order_do"
        }

        try:
            response = requests.post(url=url, headers=headers, data=json.dumps(body))
        except Exception as e:
            raise ValidationError(str(e))

        res = response.json()
        if res.get('error'):
            raise ValidationError(json.dumps(res.get('error')))
        if not res.get('success'):
            _logger.info("CRON cron_auto_done_sale_order_do NOT SUCCESS")
            return True

        data_list = res.get('data', [])
        if not data_list:
            return True
        _logger.info(f"TOTAL DATA AUTO DONE SO DO {len(data_list)}")
        
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
    def cron_synchronize_sap_flag_do_sap(self):
        icp = self.env['ir.config_parameter'].sudo()
        x_i_api_key = icp.get_param('x_i_api_key')
        ip_sap_rfc = icp.get_param('ip_sap_rfc')
        query_update_flag_do_sap = icp.get_param('query_update_flag_do_sap')
        if not x_i_api_key:
            raise ValidationError("x_i_api_key belum disetting!")
        if not ip_sap_rfc:
            raise ValidationError("ip_sap_rfc belum disetting!")
        if not query_update_flag_do_sap:
            raise ValidationError("query_update_flag_do_sap belum disetting!")

        headers = {
            "x-i-api-key": str(x_i_api_key),
            "Content-Type": "application/json"
        }

        url = f"{ip_sap_rfc}/api/v1/zfm-query-data"

        so_model = self.env['sale.order'].sudo()

        vbeln_list = [
            (so.do_sap or '').strip().replace("'", "''")
            for so in so_model.search([('do_sap', '!=', False)])
            if so.do_sap
        ]

        if not vbeln_list:
            return True
        
        vbeln_str = ",".join(f"'{v}'" for v in set(vbeln_list))
        query = query_update_flag_do_sap.format(vbeln=vbeln_str)
        body = {
            "I_QUERY": query,
            "I_MOD": "CRON cron_synchronize_sap_flag_do_sap"
        }

        try:
            response = requests.post(url=url, headers=headers, data=json.dumps(body), timeout=120)
        except Exception as e:
            raise ValidationError(str(e))

        if response.status_code != 200:
            raise ValidationError(f"{response.status_code} | {response.text}")

        res = response.json()
        if res.get('error'):
            raise ValidationError(json.dumps(res.get('error')))
        if not res.get('success'):
            _logger.info("CRON cron_synchronize_sap_flag_do_sap NOT SUCCESS")
            return True

        _logger.info(f"FLAG DO SAP UPDATED: {len(vbeln_list)}")
        
    
    @api.model
    def cron_auto_done_git(self):
        icp = self.env['ir.config_parameter'].sudo()
        x_i_api_key = icp.get_param('x_i_api_key')
        ip_sap_rfc = icp.get_param('ip_sap_rfc')
        query_auto_done_git = icp.get_param('query_auto_done_git')
        picking_type_git = icp.get_param('picking_type_git')
        if not x_i_api_key:
            raise ValidationError("x_i_api_key belum disetting!")
        if not ip_sap_rfc:
            raise ValidationError("ip_sap_rfc belum disetting!")
        if not query_auto_done_git:
            raise ValidationError("query_auto_done_git belum disetting!")
        if not picking_type_git:
            raise ValidationError("picking_type_git belum disetting!")

        headers = {
            "x-i-api-key": str(x_i_api_key),
            "Content-Type": "application/json"
        }
        url = f"{ip_sap_rfc}/api/v1/zfm-query-data"
        body = {
            "I_QUERY": str(query_auto_done_git),
            "I_MOD": "CRON cron_auto_done_git"
        }

        try:
            response = requests.post(url=url, headers=headers, data=json.dumps(body))
        except Exception as e:
            raise ValidationError(str(e))

        res = response.json()
        if res.get('error'):
            raise ValidationError(json.dumps(res.get('error')))
        if not res.get('success'):
            _logger.info("CRON cron_auto_done_git NOT SUCCESS")
            return True

        data_list = res.get('data', [])
        if not data_list:
            return True
        _logger.info(f"TOTAL DATA AUTO DONE GIT {len(data_list)}")
        
        pick_delivery_model = self.env['stock.picking'].sudo()
        for data in data_list:
            mblnr = data.get('MBLNR')
            if not mblnr:
                continue
            
            nomor_do = data.get('VBELN')
            picking = pick_delivery_model.search([
                ('sale_id.do_sap', '=', nomor_do),
                ('picking_type_id.move_type_sap', '=', str(picking_type_git)),
                ('state', '=', 'assigned'),
            ], limit=1)
            if picking:
                picking.button_validate()