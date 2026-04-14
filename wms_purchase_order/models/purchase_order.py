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
            raise ValidationError("picking_type_po pada Operation Type belum disetting!")

        po_model = self.env['purchase.order'].sudo()
        po_line_model = self.env['purchase.order.line'].sudo()
        partner_model = self.env['res.partner'].sudo()
        company_model = self.env['res.company'].sudo()
        product_model = self.env['product.product'].sudo()
        uom_model = self.env['uom.uom'].sudo()
        uom_kg = uom_model.search([('name', '=', 'kg')], limit=1)
        picking_type = self.env['stock.picking.type'].sudo().search([('move_type_sap', '=', str(picking_type_po))],limit=1)

        product_codes = {r.get('MATNR') for r in data_list if r.get('MATNR')}
        uom_names = {r.get('MEINS') for r in data_list if r.get('MEINS')}
        partners_ref = {r.get('RESWK') for r in data_list if r.get('RESWK')}
        companies_reg = {r.get('WERKS') for r in data_list if r.get('RESWK')}
        po_numbers = {r.get('EBELN') for r in data_list if r.get('EBELN')}

        products = {p.default_code: p for p in product_model.search([('default_code', 'in', list(product_codes))])}
        uoms = {u.name: u for u in uom_model.search([('name', 'in', list(uom_names))])}
        partners = {p.ref: p for p in partner_model.search([('ref', 'in', list(partners_ref))])}
        companies = {
            c.company_registry: c
            for c in company_model.search([
                ('company_registry', 'in', list(companies_reg)),
                ('sync_wms', '=', True)
            ])
        }

        existing_pos = po_model.search([('po_sto', 'in', list(po_numbers))])
        po_map = {(po.po_sto, po.company_id.id): po for po in existing_pos}

        grouped_data = defaultdict(list)
        for row in data_list:
            if row.get('EBELN'):
                grouped_data[row['EBELN']].append(row)

        for nomor_po, rows in grouped_data.items():
            first = rows[0]

            company = companies.get(first.get('WERKS'))
            partner = partners.get(first.get('RESWK'))

            if not company or not partner:
                continue

            po = po_map.get((nomor_po, company.id))

            vals_po = {
                'po_sto': nomor_po,
                'partner_id': partner.id,
                'picking_type_id': picking_type.id,
                'company_id': company.id,
                'po_sto_type': first.get('BSART'),
                'sap_synchronize': True,
                'origin': nomor_po,
            }

            if not po:
                po = po_model.create(vals_po)
                _logger.info(f"PO CREATED: {nomor_po}")
            else:
                if self._needs_update(po, vals_po):
                    po.write(vals_po)

            aggregated = defaultdict(float)

            for row in rows:
                matnr = row.get('MATNR')
                qty = float(row.get('MENGE') or 0)
                if matnr:
                    aggregated[matnr] += qty

            existing_lines = {l.product_id.id: l for l in po.order_line}

            for matnr, qty in aggregated.items():
                product = products.get(matnr)
                if not product:
                    continue

                uom_name = rows[0].get('MEINS')
                uom = uoms.get(uom_name)
                if not uom:
                    uom = product.uom_id
                if not uom:
                    uom = uom_kg
                if not uom:
                    continue

                vals_line = {
                    'order_id': po.id,
                    'product_id': product.id,
                    'name': product.name,
                    'product_qty': qty,
                    'product_uom_id': uom.id,
                    'price_unit': 0,
                    'date_planned': fields.Datetime.now(),
                }

                line = existing_lines.get(product.id)

                if line:
                    if self._needs_update(line, vals_line):
                        line.write(vals_line)
                else:
                    po_line_model.create(vals_line)