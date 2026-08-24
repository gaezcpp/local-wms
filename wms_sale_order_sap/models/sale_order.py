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
    so_sap = fields.Char(string="SO SAP", tracking=True, index=True)
    do_sap = fields.Char(string="DO SAP", tracking=True, index=True)
    po_sap = fields.Char(string="PO SAP", tracking=True, index=True)
    sales_sap_name = fields.Char(string="Sales Name", tracking=True)
    nomor_polisi_desc = fields.Text(string="Nomor Polisi", tracking=True)
    date_order_sap = fields.Date(string="Date Order", tracking=True)
    so_sto = fields.Boolean(string="STO", default=False)
    sloc_to_sloc = fields.Boolean(string="Sloc to Sloc", default=False)
    sloc_to = fields.Char(string="SLOC To", readonly=True)
    aft_mat_doc = fields.Char(string="Mat Doc")
    aft_mat_doc_year = fields.Char(string="Mat Doc Year")

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
    
    def _normalize_value(self, field_def, value):
        """Bring a raw SAP value and an ORM value into the same shape so they
        can be compared. SAP feeds `datetime` objects for Date fields, which
        would otherwise never compare equal to the stored `date`."""
        if not value:
            return False
        if field_def.type == 'date':
            return fields.Date.to_date(value)
        if field_def.type == 'datetime':
            return fields.Datetime.to_datetime(value)
        return value

    def _changed_vals(self, model, vals):
        """Return only the entries of `vals` that actually differ from the
        current values of `model`.

        Writing just this subset instead of the whole dict avoids no-op writes,
        and with them the side effects Odoo attaches to the mere *presence* of
        a key in `write()` — e.g. `sale_stock` schedules a "delivery address
        has been changed" activity on every open picking whenever
        `partner_shipping_id` is passed, even when the value is unchanged."""
        changed = {}
        for field, new_val in vals.items():
            if field not in model._fields:
                continue

            field_def = model._fields[field]
            old_val = model[field]

            if field_def.type == 'many2one':
                old_id = old_val.id if old_val else False
                if old_id != (new_val or False):
                    changed[field] = new_val

            elif field_def.type in ('many2many', 'one2many'):
                if isinstance(new_val, list):
                    new_ids = set()
                    for cmd in new_val:
                        if cmd[0] == 6:
                            new_ids = set(cmd[2])
                        elif cmd[0] == 4:
                            new_ids.add(cmd[1])
                    if set(old_val.ids) != new_ids:
                        changed[field] = new_val
                else:
                    if set(old_val.ids) != set(new_val):
                        changed[field] = new_val

            else:
                if self._normalize_value(field_def, old_val) != self._normalize_value(field_def, new_val):
                    changed[field] = new_val

        return changed

    def _needs_update(self, model, vals):
        return bool(self._changed_vals(model, vals))

    def _is_sap_sync_locked(self):
        self.ensure_one()
        return any(
            picking.state == 'done' and picking.picking_type_id.code == 'internal' and picking.picking_type_id.move_type_sap
            for picking in self.picking_ids
        )

    def _assign_order_selection(self):
        """Group each order's lines by product. When the same product appears
        on more than one line (different order_seq/qty), the line with the
        largest product_uom_qty is 'order' and the rest are 'gratis'."""
        for so in self:
            groups = defaultdict(lambda: self.env['sale.order.line'])
            for line in so.order_line:
                groups[line.product_id.id] |= line
            for lines in groups.values():
                if len(lines) <= 1:
                    lines.filtered(lambda l: l.order_selection != 'order').write({'order_selection': 'order'})
                    continue
                max_qty = max(lines.mapped('product_uom_qty'))
                gratis_lines = lines.filtered(lambda l, max_qty=max_qty: l.product_uom_qty != max_qty)
                order_lines = lines - gratis_lines
                order_lines.filtered(lambda l: l.order_selection != 'order').write({'order_selection': 'order'})
                gratis_lines.filtered(lambda l: l.order_selection != 'gratis').write({'order_selection': 'gratis'})

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
            customer_name = first.get('SOLD_TO_NAME')
            delivery_ref = first.get('SHIP_TO_CODE')
            delivery_name = first.get('SHIP_TO_NAME')
            erdat = first.get('ERDAT')
            company_registry = first.get('WERKS')
            ernam = first.get('ERNAM')
            delivery_method = (first.get('DELIVERY_METHOD') or '').strip().upper()
            stock_warehouse = first.get('LGORT')
            trucknr = first.get('TRUCKNR')
            ktokd = (first.get('KTOKD') or '').strip().upper()

            partner = partner_model.search([('ref', '=', customer_ref)], limit=1)
            if not partner:
                _logger.info(f"cron_synchronize_sap_sale_order PARTNER {customer_ref} CREATED NEW")
                partner = partner_model.create({
                    'ref': customer_ref,
                    'name': customer_name,
                    'sap_synchronize': True,
                    'type': 'contact',
                    'company_type': 'person',
                    'comment': "Created from cron_synchronize_sap_sale_order",
                })

            partner_shipping = partner_model.search([('ref', '=', delivery_ref)], limit=1)
            if not partner_shipping:
                _logger.info(f"cron_synchronize_sap_sale_order PARTNER {delivery_ref} CREATED NEW")
                partner_shipping = partner_model.create({
                    'ref': delivery_ref,
                    'name': delivery_name,
                    'sap_synchronize': True,
                    'type': 'contact',
                    'company_type': 'person',
                    'comment': "Created from cron_synchronize_sap_sale_order",
                })

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
            is_new_so = False
            sap_locked = False
            if not so:
                so = sale_order_model.create(vals)
                so.message_post(body=f"SO SAP {nomor_do} Created from Cron")
                _logger.info(f"SO Created {nomor_do}")
                is_new_so = True
            else:
                sap_locked = so._is_sap_sync_locked()
                if sap_locked:
                    _logger.info(f"SO {nomor_do} SKIPPED UPDATE: internal picking with SAP move type already exists")
                else:
                    changed_vals = self._changed_vals(so, vals)
                    if changed_vals:
                        so.with_context(update_delivery_shipping_partner=True).write(changed_vals)

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
                    if sap_locked:
                        continue
                    changed_line_vals = self._changed_vals(existing_line, {
                        'product_uom_qty': qty,
                        'product_uom_id': product_uom.id,
                    })
                    if changed_line_vals:
                        existing_line.write(changed_line_vals)
                else:
                    sale_order_line_model.create(vals_line)

            if not sap_locked:
                so._assign_order_selection()

            _logger.info(f"SO cron_synchronize_sap_sale_order {nomor_do} total line {len(rows)}")

            if is_new_so:
                so.with_context(sequence_sale_order_id=so.id).action_confirm()
                _logger.info(f"SO Confirmed cron_synchronize_sap_sale_order {nomor_do}")
            
                
    @api.model
    def cron_synhronize_sap_so_sto(self):
        data_list = self._fetch_sap_data(
            config_key='query_so_sto_sap',
            cron_name='cron_synhronize_sap_so_sto',
        )
        if not data_list:
            self.cron_synhronize_so_sloc_to_sloc()
            return

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
            kunnr = first.get('KUNNR') or first.get('SHIP_TO')
            sales_name = first.get('ERNAM')
            po_sap = first.get('EBELN')
            
            partner = partner_model.search([('ref', '=', kunnr)], limit=1)
            if not partner:
                _logger.info(f"cron_synchronize_sap_sale_order PARTNER {kunnr} CREATED NEW")
                partner = partner_model.create({
                    'ref': kunnr,
                    'name': kunnr,
                    'sap_synchronize': True,
                    'type': 'contact',
                    'company_type': 'person',
                    'comment': "Created from cron_synchronize_sap_sale_order",
                })
            
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
            is_new_so = False
            sap_locked = False
            if not so:
                so = so_model.create(vals)
                so.message_post(body=f"SO SAP {nomor_do} Created from Cron")
                _logger.info(f"SO Created {nomor_do}")
                is_new_so = True
            else:
                sap_locked = so._is_sap_sync_locked()
                if sap_locked:
                    _logger.info(f"SO STO {nomor_do} SKIPPED UPDATE: internal picking with SAP move type already exists")
                else:
                    changed_vals = self._changed_vals(so, vals)
                    if changed_vals:
                        so.write(changed_vals)

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
                elif not sap_locked:
                    changed_line_vals = self._changed_vals(existing_line, {
                        'product_uom_qty': qty,
                        'product_uom_id': product_uom.id,
                    })
                    if changed_line_vals:
                        existing_line.write(changed_line_vals)

            if not sap_locked:
                so._assign_order_selection()

            if is_new_so:
                so.with_context(sequence_sale_order_id=so.id).action_confirm()
                _logger.info(f"SO Confirmed cron_synhronize_sap_so_sto {nomor_do}")
        
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
            _logger.info(f"CRON {cron_name} NOT SUCCESS || {res}")
            return

        data_list = res.get('data', [])
        if not data_list:
            return

        _logger.info(f"TOTAL DATA {cron_name}: {len(data_list)}")

        pick_delivery_model = self.env['stock.picking'].sudo()
        for data in data_list:
            if cron_name != 'cron_auto_done_sale_order_do':
                if not data.get('MBLNR'):
                    _logger.info(f"CRON {cron_name} SKIPPED karna gaada MBLNR")
                    continue

            value = data.get(data_key)
            _logger.info(f"VALUE {value}")
            picking = pick_delivery_model.search([
                (search_field, '=', value),
                ('picking_type_id.code', '=', 'outgoing'),
                ('state', '=', 'assigned'),
            ], limit=1)
            if picking:
                picking.with_context(from_cron=True).button_validate()


    @api.model
    def cron_auto_done_all(self):
        jobs = [
            {
                'config_key': 'query_auto_done_sale_order_do_sap',
                'search_field': 'sale_id.do_sap',
                'data_key': 'VBELV',
                'cron_name': 'cron_auto_done_sale_order_do',
            },
            {
                'config_key': 'query_done_so_plan_to_plan_sap',
                'search_field': 'sale_id.do_sap',
                'data_key': 'VBELN_VL',
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
            
            nomor_do = data.get('VBELV')
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
                picking.with_context(from_cron=True).button_validate()
                
                
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
            is_new_so = False
            sap_locked = False
            if not so:
                so = so_model.create(vals)
                so.message_post(body=f"SO SAP {po_sap} Created from Cron")
                _logger.info(f"SO Created {po_sap}")
                is_new_so = True
            else:
                sap_locked = so._is_sap_sync_locked()
                if sap_locked:
                    _logger.info(f"SO SLOC to SLOC {po_sap} SKIPPED UPDATE: internal picking with SAP move type already exists")
                else:
                    changed_vals = self._changed_vals(so, vals)
                    if changed_vals:
                        so.write(changed_vals)
            
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
                elif not sap_locked:
                    changed_line_vals = self._changed_vals(existing_line, {
                        'product_uom_qty': qty,
                        'product_uom_id': product_uom_id,
                    })
                    if changed_line_vals:
                        existing_line.write(changed_line_vals)

            if not sap_locked:
                so._assign_order_selection()

            if is_new_so:
                so.with_context(sequence_sale_order_id=so.id).action_confirm()
                _logger.info(f"SO Confirmed cron_synhronize_so_sloc_to_sloc {nomor_do}")
                        
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
                    
    @api.model
    def cron_synhronize_sap_mat_doc_gr(self):
        data_list = self._fetch_sap_data(
            config_key='query_mat_doc_gr_sap',
            cron_name='cron_synhronize_sap_mat_doc_gr',
        )
        
        if not data_list:
            return True
            
        _logger.info(f"TOTAL DATA cron_synhronize_sap_mat_doc_gr: {len(data_list)}")
        picking_model = self.env['stock.picking'].sudo()
        for data in data_list:
            raw_picking_id = data.get('PICKING_ID')
            if not raw_picking_id:
                continue
                
            try:
                picking_id = int(raw_picking_id)
            except ValueError:
                _logger.warning(f"Format PICKING_ID tidak valid (bukan angka): {raw_picking_id}")
                continue

            mblnr = data.get('MBLNR')
            mjahr = data.get('MJAHR')
            
            vals = {
                'aft_mat_doc': mblnr,
                'aft_mat_doc_year': mjahr,
            }
            
            existing_picking = picking_model.browse(picking_id)
            
            if existing_picking.exists():
                changed_vals = self._changed_vals(existing_picking, vals)
                if changed_vals:
                    existing_picking.write(changed_vals)
            else:
                _logger.warning(f"Picking ID {picking_id} Skipped")
                
        return True
    
    @api.model
    def cron_synhronize_sap_mat_doc_gi(self):
        data_list = self._fetch_sap_data(
            config_key='query_mat_doc_gi_sap',
            cron_name='cron_synhronize_sap_mat_doc_gi',
        )
        
        if not data_list:
            return True
            
        _logger.info(f"TOTAL DATA cron_synhronize_sap_mat_doc_gi: {len(data_list)}")
        
        sale_order_model = self.env['sale.order'].sudo()
        
        for data in data_list:
            ebeln = data.get('EBELN') # po_sap
            vbeln = data.get('VBELN') # do_sap
            mblnr = data.get('MBLNR')
            mjahr = data.get('MJAHR')
            
            vals = {
                'aft_mat_doc': mblnr,
                'aft_mat_doc_year': mjahr,
            }
            
            domain = [('po_sap', '=', ebeln)] if ebeln else []
            so_record = sale_order_model.search(domain, limit=1) if domain else False
            
            if not so_record and vbeln:
                so_record = sale_order_model.search([('do_sap', '=', vbeln)], limit=1)
            _logger.info(f"SO RECORD {so_record}")
            if so_record:
                changed_vals = self._changed_vals(so_record, vals)
                if changed_vals:
                    so_record.write(changed_vals)

                valid_pickings = so_record.picking_ids.filtered(lambda p: p.picking_type_id.code == 'outgoing')
                _logger.info(f"VALID PICK {valid_pickings}")
                for picking in valid_pickings:
                    changed_picking_vals = self._changed_vals(picking, vals)
                    if changed_picking_vals:
                        picking.write(changed_picking_vals)
            # else:
            #     _logger.warning(f"Sale Order tidak ditemukan untuk PO SAP: {ebeln} atau DO SAP: {vbeln}")
                
        return True

    @api.model
    def cron_synhronize_sap_mat_doc_aft(self):
        data_list = self._fetch_sap_data(
            config_key='query_mat_doc_aft_sap',
            cron_name='cron_synhronize_sap_mat_doc_aft',
        )
        if not data_list:
            return True
            
        _logger.info(f"TOTAL DATA cron_synhronize_sap_mat_doc_aft: {len(data_list)}")
        
        aft_model = self.env['quality.packages'].sudo()
        aft_summary_model = self.env['quality.packages.summary.line'].sudo()
        
        from collections import defaultdict
        grouped_data = defaultdict(list)
        
        for row in data_list:
            raw_picking_id = row.get('PICKING_ID')
            try:
                picking_id = int(raw_picking_id)
            except (ValueError, TypeError):
                _logger.warning(f"Format PICKING_ID tidak valid: {raw_picking_id}")
                continue
            if picking_id:
                grouped_data[picking_id].append(row)
        
        for picking_id, rows in grouped_data.items():
            existing_aft = aft_model.browse(picking_id)
            if not existing_aft.exists():
                _logger.info(f"cron_synhronize_sap_mat_doc_aft AFT ID {picking_id} skipped")
                continue
            
            for row in rows:
                raw_line_id = row.get('LINE_ID')
                mblnr = row.get('MBLNR')
                mjahr = row.get('MJAHR')
                
                try:
                    line_id = int(raw_line_id)
                except (ValueError, TypeError):
                    _logger.warning(f"Format LINE_ID tidak valid: {raw_line_id}")
                    continue
                
                existing_line = aft_summary_model.search([
                    ('quality_packages_id', '=', existing_aft.id),
                    ('id', '=', line_id)
                ], limit=1)
                
                vals = {
                    'aft_mat_doc': mblnr,
                    'aft_mat_doc_year': mjahr,
                }
                
                if existing_line:
                    # Cara benar mengecek apakah model memiliki field tersebut
                    if 'aft_mat_doc' in existing_line._fields and 'aft_mat_doc_year' in existing_line._fields:
                        changed_vals = self._changed_vals(existing_line, vals)
                        if changed_vals:
                            existing_line.write(changed_vals)

    @api.model
    def cron_run_mat_doc(self):
        crons = [
            self.cron_synhronize_sap_mat_doc_gr,
            self.cron_synhronize_sap_mat_doc_gi,
            self.cron_synhronize_sap_mat_doc_aft,
        ]
        for cron in crons:
            try:
                cron()
            except Exception as e:
                _logger.error(f"cron_run_mat_doc: {cron.__name__} FAILED — {e}")
        
        return True