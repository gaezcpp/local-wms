from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import datetime
from collections import defaultdict
import requests
import json
import logging
import re
_logger = logging.getLogger(__name__)


class InheritSaleOrderSAP(models.Model):
    _inherit = 'sale.order'
    
    is_sap = fields.Boolean(string="SAP", default=False, tracking=True)
    so_sap = fields.Char(string="SO SAP", tracking=True)
    do_sap = fields.Char(string="DO SAP", tracking=True)
    sales_sap_name = fields.Char(string="Sales Name", tracking=True)
    nopol_description = fields.Char(string="Nomor Polisi", tracking=True)
    
    @api.depends('name', 'do_sap')
    def _compute_display_name(self):
        for rec in self:
            so_name = rec.name if rec.name else "(Empty)"
            do_sap = rec.do_sap if rec.do_sap else "-"
            name = '%s - [%s]' % (so_name, do_sap)
            rec.display_name = name
    
    # def _prepare_picking(self):
    #     res = super()._prepare_picking()
    #     res['so_id'] = self.id
    #     return res
    
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

            partner = partner_model.search([('ref', '=', customer_ref)], limit=1)
            if not partner:
                _logger.info(f"Customer {customer_ref} SKIPPED")
                continue

            partner_shipping = partner_model.search([('ref', '=', delivery_ref)], limit=1)
            if not partner_shipping:
                _logger.info(f"Delivery {delivery_ref} SKIPPED")
                continue

            company = company_model.search([('company_registry', '=', company_registry)], limit=1)
            if not company:
                _logger.info(f"Company {company_registry} SKIPPED")
                continue

            order_date = False
            if erdat and len(erdat) == 8:
                order_date = datetime.strptime(erdat, "%Y%m%d").date()

            so = sale_order_model.search([('do_sap', '=', nomor_do)], limit=1)
            if not so:
                vals = {
                    'is_sap': True,
                    'do_sap': nomor_do,
                    'so_sap': nomor_so,
                    'partner_id': partner.id,
                    'partner_shipping_id': partner_shipping.id,
                    'date_order': order_date,
                    'sales_sap_name': ernam,
                    'company_id': company.id,
                }
                so = sale_order_model.create(vals)
                so.message_post(body=f"SO SAP {nomor_do} Created from Cron")
                so.action_confirm()
                _logger.info(f"SO Created {nomor_do}")

            for row in rows:
                product_code = row.get('MATNR')
                if not product_code:
                    continue
                product = product_model.search([('default_code', '=', product_code)], limit=1)
                if not product:
                    _logger.info(f"Product {product_code} SKIPPED")
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

                if existing_line:
                    continue

                sale_order_line_model.create({
                    'order_id': so.id,
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'product_uom_id': product_uom.id,
                })

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

            nopol_description = "\n".join(nopol_lines)
            if so.nopol_description != nopol_description:
                so.write({'nopol_description': nopol_description})
                _logger.info(f"Nopol updated DO {so.do_sap}")