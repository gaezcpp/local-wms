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


class InheritPurchaseOrder(models.Model):
    _inherit = 'purchase.order'
    
    po_sto = fields.Char(string="PO STO")
    po_sto_type = fields.Char(string="PO STO Type")
    sap_synchronize = fields.Boolean(string="SAP Synchronize", default=False)
    sloc_to_sloc = fields.Boolean(string="Sloc to Sloc", default=False)
    nomor_polisi_desc = fields.Text(string="Nomor Polisi")
    
    def _needs_update(self, record, vals):
        for field, val in vals.items():
            if field not in record._fields:
                continue

            current = record[field]

            if record._fields[field].type == 'many2one':
                if (current.id if current else False) != val:
                    return True
            else:
                if (current or False) != (val or False):
                    return True
        return False
    
    @api.model
    def cron_synchronize_sap_po_sto(self):
        icp = self.env['ir.config_parameter'].sudo()
        x_i_api_key = icp.get_param('x_i_api_key')
        ip_sap_rfc = icp.get_param('ip_sap_rfc')
        query_po_sto_sap = icp.get_param('query_po_sto_sap')

        if not x_i_api_key:
            raise ValidationError("x_i_api_key belum disetting!")
        if not ip_sap_rfc:
            raise ValidationError("ip_sap_rfc belum disetting!")
        if not query_po_sto_sap:
            raise ValidationError("query_po_sto_sap belum disetting!")

        headers = {
            "x-i-api-key": str(x_i_api_key),
            "Content-Type": "application/json"
        }

        url = f"{ip_sap_rfc}/api/v1/zfm-query-data"

        body = {
            "I_QUERY": str(query_po_sto_sap),
            "I_MOD": "CRON cron_synchronize_sap_po_sto"
        }

        try:
            response = requests.post(url=url, headers=headers, data=json.dumps(body))
        except Exception as e:
            raise ValidationError(str(e))

        res = response.json()
        if res.get('error'):
            raise ValidationError(json.dumps(res.get('error')))
        if not res.get('success'):
            _logger.info("CRON cron_synchronize_sap_po_sto NOT SUCCESS")
            return True

        data_list = res.get('data', [])
        if not data_list:
            return True
        _logger.info(f"TOTAL DATA SAP {len(data_list)}")
        
        picking_type_po = self.env['ir.config_parameter'].sudo().get_param('picking_type_po')
        if not picking_type_po:
            raise ValidationError("picking_type_po belum disetting!")
        
        po_model = self.env['purchase.order'].sudo()
        po_line_model = self.env['purchase.order.line'].sudo()
        partner_model = self.env['res.partner'].sudo()
        company_model = self.env['res.company'].sudo()
        product_model = self.env['product.product'].sudo()
        uom_model = self.env['uom.uom'].sudo()
        location_model = self.env['stock.location'].sudo()
        operation_type_model = self.env['stock.picking.type'].sudo()
        
        grouped_data = defaultdict(list)
        
        for row in data_list:
            nomor_po = row.get('EBELN')
            if nomor_po:
                grouped_data[nomor_po].append(row)
        
        for nomor_po, rows in grouped_data.items():
            first = rows[0]
            arrdate = first.get('ARRDATE')
            nomor_polisi_desc = first.get('TRUCKNR')
            partner_ref = first.get('DONR')
            company_registry = first.get('PENERIMA')
            partner = first.get('PENGIRIM')
            stock_warehouse = first.get('LGORT')
            po_sto_type = first.get('BSART')
            
            partner = partner_model.search([('ref', '=', partner)], limit=1)
            if not partner:
                _logger.info(f"cron_synchronize_sap_po_sto partner {partner} skipped")
                continue
            
            company = company_model.search([('company_registry', '=', company_registry),('sync_wms', '=', True)], limit=1)
            if not company:
                _logger.info(f"cron_synchronize_sap_po_sto company {company_registry} skipped")
                continue
            
            lot_stock = location_model.search([
                ('sloc_id.code', '=', stock_warehouse),
                ('location_id.usage', '=', 'view'),
                ('company_id', '=', company.id)
            ], limit=1)
            if not lot_stock:
                _logger.info(f"cron_synchronize_sap_po_sto sloc code {stock_warehouse} skipped")
                continue
            
            picking_type = operation_type_model.search([
                ('move_type_sap', '=', str(picking_type_po)),
                ('warehouse_id.lot_stock_id', '=', lot_stock.id),
                ('company_id', '=', company.id)
            ], limit=1)
            if not picking_type:
                _logger.info(f"cron_synchronize_sap_po_sto move type {picking_type_po} & warehouse lot stock {lot_stock.name} skipped")
                continue
            
            po_date = False
            if arrdate and len(arrdate) == 8:
                po_date = datetime.strptime(arrdate, "%Y%m%d")
                
            po = po_model.search([
                ('po_sto', '=', nomor_po),
                ('company_id', '=', company.id),
            ], limit=1)
            
            vals_po = {
                'po_sto': nomor_po,
                'partner_id': partner.id,
                'partner_ref': partner_ref,
                'picking_type_id': picking_type.id if picking_type else False,
                'company_id': company.id,
                'po_sto_type': po_sto_type,
                'sap_synchronize': True,
                'origin': nomor_po,
                'nomor_polisi_desc': nomor_polisi_desc,
            }
            
            if not po:
                po = po_model.create(vals_po)
                po.button_confirm()
                po.message_post(body=f"PO STO SAP {nomor_po} Created From CRON")
                _logger.info(f"SO Created {nomor_po}")
            else:
                if self._needs_update(po, vals_po):
                    po.write(vals_po)
            
            for row in rows:
                product_code = (row.get('MATNR') or '').lstrip('0')
                if not product_code:
                    continue
                product = product_model.search([('default_code', '=', product_code), ('company_id', '=', company.id)], limit=1)
                if not product:
                    _logger.info(f"cron_synchronize_sap_po_sto product {product_code} skipped")
                    continue
                
                delivery_uom = (row.get('LDTYPE') or '').strip()
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
                
                qty = float(row.get('DOQTY') or 0)
                posnr = (row.get('POSNR') or "").lstrip('0')
                po_seq = (row.get('VGPOS') or "").lstrip('0')
                existing_line = po_line_model.search([
                    ('order_id', '=', po.id),
                    ('product_id', '=', product.id),
                    ('sap_sequence', '=', posnr),
                ], limit=1)
                
                vals_line = {
                    'order_id': po.id,
                    'product_id': product.id,
                    'name': product.name,
                    'product_qty': qty,
                    'product_uom_id': product_uom.id,
                    'price_unit': 0,
                    'date_planned': fields.Datetime.now(),
                    'sap_sequence': posnr,
                    'order_seq': po_seq,
                }
                
                if not existing_line:
                    po_line_model.create(vals_line)
                else:
                    if self._needs_update(existing_line, vals_line):
                        existing_line.write({
                            'product_uom_qty': qty,
                            'product_uom_id': product_uom.id,
                        })
    
    @api.model
    def cron_synhronize_purchase_sloc_to_sloc(self):
        icp = self.env['ir.config_parameter'].sudo()
        x_i_api_key = icp.get_param('x_i_api_key')
        ip_sap_rfc = icp.get_param('ip_sap_rfc')
        query_purchase_sloc_to_sloc_sap = icp.get_param('query_purchase_sloc_to_sloc_sap')

        if not x_i_api_key:
            raise ValidationError("x_i_api_key belum disetting!")
        if not ip_sap_rfc:
            raise ValidationError("ip_sap_rfc belum disetting!")
        if not query_purchase_sloc_to_sloc_sap:
            raise ValidationError("query_purchase_sloc_to_sloc_sap belum disetting!")

        headers = {
            "x-i-api-key": str(x_i_api_key),
            "Content-Type": "application/json"
        }
        url = f"{ip_sap_rfc}/api/v1/zfm-query-data"
        body = {
            "I_QUERY": str(query_purchase_sloc_to_sloc_sap),
            "I_MOD": "CRON cron_synhronize_purchase_sloc_to_sloc"
        }

        try:
            response = requests.post(url=url, headers=headers, data=json.dumps(body))
        except Exception as e:
            raise ValidationError(str(e))

        res = response.json()

        if res.get('error'):
            raise ValidationError(json.dumps(res.get('error')))

        if not res.get('success'):
            _logger.info("CRON cron_synhronize_purchase_sloc_to_sloc NOT SUCCESS")
            return True

        data_list = res.get('data', [])
        _logger.info(f"TOTAL DATA SAP {len(data_list)}")

        if not data_list:
            return True
        
        purchase_sloc_to_sloc = self.env['ir.config_parameter'].sudo().get_param('purchase_sloc_to_sloc')
        if not purchase_sloc_to_sloc:
            raise ValidationError("picking_type_po belum disetting!")
        
        po_model = self.env['purchase.order'].sudo()
        po_line_model = self.env['purchase.order.line'].sudo()
        partner_model = self.env['res.partner'].sudo()
        company_model = self.env['res.company'].sudo()
        product_model = self.env['product.product'].sudo()
        unit_model = self.env['uom.uom'].sudo()
        location_model = self.env['stock.location'].sudo()
        operation_type_model = self.env['stock.picking.type'].sudo()
        
        grouped_data = defaultdict(list)
        
        for row in data_list:
            nomor_po = row.get('EBELN')
            if nomor_po:
                grouped_data[nomor_po].append(row)
        
        for nomor_po, rows in grouped_data.items():
            first = rows[0]
            trucknr = first.get('TRUCKNR')
            arrdate = first.get('ARRDATE')
            werks = first.get('WERKS')
            sloc = first.get('KESLOC') or first.get('SLOCTO')
            
            company = company_model.search([('company_registry', '=', werks)], limit=1)
            if not company:
                _logger.info(f"cron_synhronize_purchase_sloc_to_sloc company {werks} skipped")
                continue
            
            partner = partner_model.search([('ref', '=', werks)], limit=1)
            if not partner:
                _logger.info(f"cron_synhronize_purchase_sloc_to_sloc partner {werks} skipped")
                continue
            
            lot_stock = location_model.search([
                ('sloc_id.code', '=', sloc),
                ('location_id.usage', '=', 'view'),
                ('company_id', '=', company.id)
            ], limit=1)
            if not lot_stock:
                _logger.info(f"cron_synhronize_purchase_sloc_to_sloc sloc code {sloc} skipped")
                continue
            
            picking_type = operation_type_model.search([
                ('move_type_sap', '=', str(purchase_sloc_to_sloc)),
                ('warehouse_id.lot_stock_id', '=', lot_stock.id),
                ('company_id', '=', company.id)
            ], limit=1)
            if not picking_type:
                _logger.info(f"cron_synchronize_sap_po_sto move type {purchase_sloc_to_sloc} & warehouse lot stock {lot_stock.name} skipped")
                continue
            
            if arrdate and len(arrdate) == 8:
                arrdate = datetime.strptime(arrdate, "%Y%m%d")
                
            po_sts = po_model.search([
                ('po_sto', '=', nomor_po),
                ('company_id', '=', company.id),
                ('sloc_to_sloc', '=', True)
            ], limit=1)
            
            vals_po_sts = {
                'po_sto': nomor_po,
                'partner_id': partner.id,
                'partner_ref': partner.ref,
                'picking_type_id': picking_type.id if picking_type else False,
                'date_order': arrdate,
                'company_id': company.id,
                'sap_synchronize': True,
                'sloc_to_sloc': True,
                'origin': nomor_po,
                'nomor_polisi_desc': trucknr,
            }
            
            if not po_sts:
                po_sts = po_model.create(vals_po_sts)
                po_sts.button_confirm()
                po_sts.message_post(body=f"PO Sloc To Sloc SAP {nomor_po} Created From CRON")
                _logger.info(f"PO Sloc to Sloc Created {nomor_po}")
            else:
                if self._needs_update(po_sts, vals_po_sts):
                    po_sts.write(vals_po_sts)
            
            for row in rows:
                product_code = (row.get('MATNR') or '').lstrip('0')
                if not product_code:
                    continue
                product = product_model.search([('default_code', '=', product_code), ('company_id', '=', company.id)], limit=1)
                if not product:
                    _logger.info(f"cron_synchronize_sap_po_sto product {product_code} skipped")
                    continue
                
                delivery_uom = (row.get('UOE') or '').lstrip()
                uom_numerator = float(row.get('UMREZ'))
                uom_denominator = float(row.get('UMREN'))
                product_uom = product.uom_bag_id
                if delivery_uom and delivery_uom.upper() != "KG":
                    ratio = float(uom_numerator) / float(uom_denominator)
                    ratio = int(ratio) if ratio.is_integer() else ratio
                    uom_name = f"{delivery_uom} {ratio}"
                    uom = unit_model.search([('name', '=', uom_name)], limit=1)
                    if uom:
                        product_uom = uom
                
                qty = float(row.get('QTYPO') or 0)
                seqnr = (row.get('SEQNR') or "").lstrip('0')
                ebelp = (row.get('EBELP') or "").lstrip('0')
                existing_line = po_line_model.search([
                    ('order_id', '=', po_sts.id),
                    ('product_id', '=', product.id),
                    ('order_seq', '=', ebelp),
                ], limit=1)
                
                vals_line = {
                    'order_id': po_sts.id,
                    'product_id': product.id,
                    'name': product.name,
                    'product_qty': qty,
                    'product_uom_id': product_uom.id,
                    'price_unit': 0,
                    'date_planned': fields.Datetime.now(),
                    'sap_sequence': seqnr,
                    'order_seq': ebelp,
                }
                
                if not existing_line:
                    po_line_model.create(vals_line)
                else:
                    if self._needs_update(existing_line, vals_line):
                        existing_line.write({
                            'product_uom_qty': qty,
                            'product_uom_id': product_uom.id,
                        })