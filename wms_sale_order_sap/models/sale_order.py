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
    sales_sap_name = fields.Char(string="Sales Name", tracking=True)
    nomor_polisi_desc = fields.Text(string="Nomor Polisi", tracking=True)
    date_order_sap = fields.Date(string="Date Order", tracking=True)

    def now_jakarta(self):
        tz = pytz.timezone('Asia/Jakarta')
        now_jakarta = datetime.now(tz)
        return now_jakarta

    # def _prepare_picking(self):
    #     res = super()._prepare_picking()
    #     _logger.info(f"PREPARE PICKING {res}")
    #     jkt_now = self.now_jakarta()
    #     now_hour = jkt_now.strftime("%H%M")
    #     prod_shift = self.env['production.shift'].sudo().search([
    #         ('date_start', '<=', now_hour),
    #         ('date_end', '>=', now_hour),
    #     ], limit=1)
    #     _logger.info(f"PRODDDDDD {prod_shift} {now_hour}")
    #     if prod_shift:
    #         res['production_shift_id'] = prod_shift.id
    #     if self.do_sap:
    #         po_sap = self.env['production.order.sap'].sudo().search([('po_number', '=', self.do_sap)], limit=1)
    #         if po_sap:
    #             res['po_sap_id'] = po_sap.id
    #     return res
    
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

            partner = partner_model.search([('ref', '=', customer_ref)], limit=1)
            if not partner:
                _logger.info(f"Customer {customer_ref} SKIPPED")
                continue

            partner_shipping = partner_model.search([('ref', '=', delivery_ref)], limit=1)
            if not partner_shipping:
                _logger.info(f"Delivery {delivery_ref} SKIPPED")
                continue

            company = company_model.search([
                ('company_registry', '=', company_registry),
                ('sync_wms', '=', True),
                ('sync_pm', '=', False),
            ], limit=1)
            if not company:
                _logger.info(f"Company {company_registry} SKIPPED")
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
            }
            if not so:
                so = sale_order_model.create(vals)
                so.message_post(body=f"SO SAP {nomor_do} Created from Cron")
                so.action_confirm()
                _logger.info(f"SO Created {nomor_do}")
            # else:
            #     if self._needs_update(so, vals):
            #         so.write(vals)
            #         so.message_post(body=f"SO Updated {so.name} | {so.do_sap}")
            #         _logger.info(f"SO Updated {so.name} | {so.do_sap}")

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
                existing_line = sale_order_line_model.search([
                    ('order_id', '=', so.id),
                    ('product_id', '=', product.id)
                ], limit=1)

                vals_line = {
                    'order_id': so.id,
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'product_uom_id': product_uom.id,
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