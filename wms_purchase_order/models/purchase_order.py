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
            _logger.info(f"CRON {cron_name} NOT SUCCESS || {res}")
            return []

        data_list = res.get('data', [])
        _logger.info(f"CRON {cron_name} - TOTAL DATA: {len(data_list)}")
        return data_list
    
    @api.model
    def cron_synchronize_sap_po_sto(self):
        data_list = self._fetch_sap_data(
            config_key='query_po_sto_sap',
            cron_name='cron_synchronize_sap_po_sto',
        )
        if not data_list:
            return True
        _logger.info(f"TOTAL DATA cron_synchronize_sap_po_sto: {len(data_list)}")
        
        picking_type_po = self.env['ir.config_parameter'].sudo().get_param('picking_type_po')
        if not picking_type_po:
            raise ValidationError("picking_type_po belum disetting!")
        
        po_model = self.env['purchase.order'].sudo()
        po_line_model = self.env['purchase.order.line'].sudo()
        partner_model = self.env['res.partner'].sudo()
        company_model = self.env['res.company'].sudo()
        product_model = self.env['product.product'].sudo()
        uom_model = self.env['uom.uom'].sudo()
        operation_type_model = self.env['stock.picking.type'].sudo()
        wh_model = self.env['stock.warehouse'].sudo()
        
        grouped_data = defaultdict(list)
        
        for row in data_list:
            nomor_po = row.get('EBELN')
            if nomor_po:
                grouped_data[nomor_po].append(row)
        
        for nomor_po, rows in grouped_data.items():
            first = rows[0]
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
            
            warehouse = wh_model.search([
                ('lot_stock_id.sloc_id.code', '=', stock_warehouse),
                ('company_id', '=', company.id)
            ], limit=1)
            if not warehouse:
                _logger.info(f"cron_synchronize_sap_po_sto sloc code {stock_warehouse} skipped")
                continue
            
            picking_type = operation_type_model.search([
                ('move_type_sap', '=', str(picking_type_po)),
                ('warehouse_id', '=', warehouse.id),
                ('company_id', '=', company.id)
            ], limit=1)
            if not picking_type:
                _logger.info(f"cron_synchronize_sap_po_sto move type {picking_type_po} & warehouse lot stock {warehouse.lot_stock_id.sloc_id.code} skipped")
                continue
                
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
            
            is_new_po = False
            if not po:
                po = po_model.create(vals_po)
                po.message_post(body=f"PO STO SAP {nomor_po} Created From CRON")
                _logger.info(f"SO Created {nomor_po}")
                is_new_po = True
            else:
                if self._needs_update(po, vals_po):
                    po.write(vals_po)
            
            for row in rows:
                product_code = (row.get('MATNR') or '').lstrip('0')
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
            
            if is_new_po:
                po.button_confirm()
                _logger.info(f"PO Confirmed {nomor_po}")
    
    @api.model
    def cron_synhronize_purchase_sloc_to_sloc(self):
        data_list = self._fetch_sap_data(
            config_key='query_purchase_sloc_to_sloc_sap',
            cron_name='cron_synhronize_purchase_sloc_to_sloc',
        )
        if not data_list:
            return True
        _logger.info(f"TOTAL DATA cron_synhronize_purchase_sloc_to_sloc: {len(data_list)}")
        
        purchase_sloc_to_sloc = self.env['ir.config_parameter'].sudo().get_param('purchase_sloc_to_sloc')
        if not purchase_sloc_to_sloc:
            raise ValidationError("picking_type_po belum disetting!")
        
        po_model = self.env['purchase.order'].sudo()
        po_line_model = self.env['purchase.order.line'].sudo()
        partner_model = self.env['res.partner'].sudo()
        company_model = self.env['res.company'].sudo()
        product_model = self.env['product.product'].sudo()
        unit_model = self.env['uom.uom'].sudo()
        warehouse_model = self.env['stock.warehouse'].sudo()
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
            
            company = company_model.search([('company_registry', '=', werks),('sync_wms', '=', True)], limit=1)
            if not company:
                _logger.info(f"cron_synhronize_purchase_sloc_to_sloc company {werks} skipped")
                continue
            
            partner = partner_model.search([('ref', '=', werks)], limit=1)
            if not partner:
                _logger.info(f"cron_synhronize_purchase_sloc_to_sloc partner {werks} skipped")
                continue
            
            warehouse = warehouse_model.search([
                ('lot_stock_id.sloc_id.code', '=', sloc),
                ('company_id', '=', company.id),
            ], limit=1)
            if not warehouse:
                _logger.info(f"cron_synhronize_purchase_sloc_to_sloc sloc code {sloc} skipped")
                continue
            
            picking_type = operation_type_model.search([
                ('move_type_sap', '=', str(purchase_sloc_to_sloc)),
                ('warehouse_id', '=', warehouse.id),
                ('company_id', '=', company.id)
            ], limit=1)
            if not picking_type:
                _logger.info(f"cron_synchronize_sap_po_sto move type {purchase_sloc_to_sloc} & warehouse lot stock {warehouse.name} skipped")
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
            
            is_new_po = False
            if not po_sts:
                po_sts = po_model.create(vals_po_sts)
                po_sts.message_post(body=f"PO Sloc To Sloc SAP {nomor_po} Created From CRON")
                _logger.info(f"PO Sloc to Sloc Created {nomor_po}")
                is_new_po = True
            else:
                if self._needs_update(po_sts, vals_po_sts):
                    po_sts.write(vals_po_sts)
            
            for row in rows:
                product_code = (row.get('MATNR') or '').lstrip('0')
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
                        
            if is_new_po:
                po_sts.button_confirm()
                _logger.info(f"PO Confirmed {nomor_po}")