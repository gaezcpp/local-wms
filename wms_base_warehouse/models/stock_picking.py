from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
from datetime import datetime
from collections import defaultdict
import requests
import json
import logging
_logger = logging.getLogger(__name__)

class InheritBaseStockPicking(models.Model):
    _inherit = 'stock.picking'
    
    over_delivery = fields.Boolean(string="Over Delivery", tracking=True)
    production_shift_id = fields.Many2one(comodel_name='production.shift', string="Shift", tracking=True)
    production_order_name = fields.Char(string="Production Order", tracking=True)
    product_packaging_ids = fields.One2many('picking.packaging.line', 'picking_id')
    synchronize_sap = fields.Boolean(string="Synchronize SAP", default=False, tracking=True)
    production_only = fields.Boolean(related='picking_type_id.production_only', store=True, readonly=True)
    sloc_to = fields.Char(string="SLOC To")
    
    def _create_backorder(self, backorder_moves=None):
        backorders = super()._create_backorder(backorder_moves=backorder_moves)
        backorders.write({'synchronize_sap': False})
        return backorders
    
    def copy(self, default=None):
        default = dict(default or {})
        default['synchronize_sap'] = False
        return super().copy(default)
    
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
    def cron_synhronize_sap_sales_return(self):
        icp = self.env['ir.config_parameter'].sudo()
        x_i_api_key = icp.get_param('x_i_api_key')
        ip_sap_rfc = icp.get_param('ip_sap_rfc')
        query_sales_return_sap = icp.get_param('query_sales_return_sap')

        if not x_i_api_key:
            raise ValidationError("x_i_api_key belum disetting!")
        if not ip_sap_rfc:
            raise ValidationError("ip_sap_rfc belum disetting!")
        if not query_sales_return_sap:
            raise ValidationError("query_sales_return_sap belum disetting!")

        headers = {
            "x-i-api-key": str(x_i_api_key),
            "Content-Type": "application/json"
        }

        url = f"{ip_sap_rfc}/api/v1/zfm-query-data"

        body = {
            "I_QUERY": str(query_sales_return_sap),
            "I_MOD": "CRON cron_synhronize_sap_sales_return"
        }

        try:
            response = requests.post(url=url, headers=headers, data=json.dumps(body))
        except Exception as e:
            raise ValidationError(str(e))

        res = response.json()

        if res.get('error'):
            raise ValidationError(json.dumps(res.get('error')))

        if not res.get('success'):
            _logger.info("CRON cron_synhronize_sap_sales_return NOT SUCCESS")
            return True

        data_list = res.get('data', [])

        if not data_list:
            return True

        _logger.info(f"TOTAL DATA cron_synhronize_sap_sales_return {len(data_list)}")

        picking_model = self.env['stock.picking'].sudo()
        move_model = self.env['stock.move'].sudo()
        wh_model = self.env['stock.warehouse'].sudo()
        operation_type_model = self.env['stock.picking.type'].sudo()
        partner_model = self.env['res.partner'].sudo()
        company_model = self.env['res.company'].sudo()
        product_model = self.env['product.product'].sudo()
        uom_model = self.env['uom.uom'].sudo()
        # uom_kg = uom_model.search([('name', '=', 'kg')], limit=1)

        grouped_data = defaultdict(list)

        for row in data_list:
            vblen = row.get('VBLEN')
            if vblen:
                grouped_data[vblen].append(row)
        for vblen, rows in grouped_data.items():
            first = rows[0]
            werks = (first.get('WERKS') or '').strip()
            arrdate = (first.get('ARRDATE') or '').strip()
            lgort = (first.get('LGORT') or '').strip()
            trucknr = (first.get('TRUCKNR') or '').strip()
            kunnr = (first.get('KUNNR') or '').strip()
            bktxt = (first.get('BKTXT') or '').strip()
            note = '\n'.join(filter(None, [bktxt, trucknr]))
            
            company = company_model.search([('company_registry', '=', werks),('sync_wms', '=', True)], limit=1)
            if not company:
                _logger.info(f"cron_synhronize_sap_sales_return COMPANY {werks} SKIPPED")
                continue

            partner = partner_model.search([('ref', '=', kunnr)], limit=1)
            if not partner:
                _logger.info(f"cron_synhronize_sap_sales_return PARTNER {kunnr} SKIPPED")
                continue
            
            sales_retur_barcode_sap = icp.get_param('sales_retur_barcode_sap')   
            warehouse = wh_model.search([
                ('lot_stock_id.sloc_id.code', '=', lgort),
                ('company_id', '=', company.id),
            ], limit=1)
            if not warehouse:
                _logger.info(f"cron_synhronize_sap_sales_return WAREHOUSE lgort={lgort} SKIPPED")
                continue
            
            operation_type = operation_type_model.search([
                ('barcode', '=', str(sales_retur_barcode_sap)),
                ('warehouse_id', '=', warehouse.id),
                ('company_id', '=', company.id)
            ], limit=1)
            if not operation_type:
                _logger.info(f"cron_synhronize_sap_sales_return OPERATION TYPE {sales_retur_barcode_sap} SKIPPED")
                continue

            schedule_date = False
            if arrdate and len(arrdate) == 8:
                schedule_date = datetime.strptime(arrdate, "%Y%m%d")

            sales_return = picking_model.search([('origin', '=', vblen),('company_id', '=', company.id),('state', '!=', 'cancel')], limit=1)
            vals = {
                'partner_id': partner.id,
                'picking_type_id': operation_type.id,
                'location_dest_id': operation_type.default_location_dest_id.id,
                'synchronize_sap': True,
                'origin': vblen,
                'scheduled_date': schedule_date,
                'company_id': company.id,
                'note': note,
            }
            if not sales_return:
                sales_return = sales_return.create(vals)
                sales_return.message_post(body=f"SALES RETURN {vblen} Created from Cron")
                _logger.info(f"SALES RETURN {vblen}")
            else:
                if self._needs_update(sales_return, vals):
                    sales_return.write(vals)

            for row in rows:
                matnr = (row.get('MATNR') or '').lstrip('0')
                product = product_model.search([('default_code', '=', matnr), ('company_id', '=', company.id)], limit=1)
                if not product:
                    _logger.info(f"cron_synhronize_sap_sales_return PRODUCT {matnr} SKIPPED")
                    continue
                
                uom_bag = (row.get('VRKME') or '')
                umrez = float(row.get('UMREZ') or 1)
                umren = float(row.get('UMREN') or 1)
                product_uom = product.uom_bag_id
                if uom_bag and uom_bag.upper() != "KG":
                    ratio = float(umrez) / float(umren)
                    ratio = int(ratio) if ratio.is_integer() else ratio
                    uom_name = f"{uom_bag} {ratio}"
                    uom = uom_model.search([('name', '=', uom_name)], limit=1)
                    if uom:
                        product_uom = uom

                qty = float(row.get('DOQTY') or 0)
                posnr = (row.get('POSNR') or "").lstrip('0')
                existing_line = move_model.search([
                    ('picking_id', '=', sales_return.id),
                    ('product_id', '=', product.id),
                    ('sap_seq', '=', posnr),
                    ('order_seq', '=', posnr)
                ], limit=1)

                vals_line = {
                    'picking_id': sales_return.id,
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'quantity': qty,
                    'product_uom': product_uom.id,
                    'location_id': sales_return.location_id.id,
                    'location_dest_id': sales_return.location_dest_id.id,
                    'sap_seq': posnr,
                    'order_seq': posnr,
                    'company_id': company.id,
                }
                
                if existing_line:
                    if self._needs_update(existing_line, vals_line):
                        existing_line.write({'product_uom_qty': qty})
                else:
                    move_model.create(vals_line)

            _logger.info(f"SALES RETUR {vgbel} total line {len(rows)}")