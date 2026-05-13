from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import datetime
import requests
import json
import logging
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
    product_id = fields.Many2one(comodel_name='product.template', string="Product", tracking=True)
    uom_id = fields.Many2one(comodel_name='uom.uom', string="UoM", tracking=True)
    order_qty = fields.Float(string="Order Qty", tracking=True)
    company_registry = fields.Char(string="Company Registry", tracking=True)
    company_id = fields.Many2one(comodel_name='res.company', string="Company", default=lambda self: self.env.company, tracking=True)
    state = fields.Selection([
        ('open', 'Open'),
        ('teco', 'TECO'),
        ('closed', 'Closed'),
    ], string="Status", default='open', tracking=True)
    created_user = fields.Char(string="Created By", tracking=True)
    status_teco = fields.Char(string="TECO Status", tracking=True)
    sap_pp = fields.Boolean(string="SAP PP", default=False)
    
    @api.model
    def cron_synchronize_sap_production_order(self):
        icp = self.env['ir.config_parameter'].sudo()
        x_i_api_key = icp.get_param('x_i_api_key')
        ip_sap_rfc = icp.get_param('ip_sap_rfc')
        query_production_order_sap = icp.get_param('query_production_order_sap')
        
        if not x_i_api_key:
            raise ValidationError("x_i_api_key belum disetting!")
        if not ip_sap_rfc:
            raise ValidationError("ip_sap_rfc belum disetting!")
        if not query_production_order_sap:
            raise ValidationError("query_production_order_sap belum disetting!")
        
        headers = {
            "x-i-api-key": str(x_i_api_key),
            "Content-Type": "application/json"
        }
        
        url = f"{str(ip_sap_rfc)}/api/v1/zfm-query-data"
        body = {
            "I_QUERY": str(query_production_order_sap),
            "I_MOD": "CRON cron_synchronize_sap_production_order"
        }
        
        try:
            response = requests.post(url=url, headers=headers, data=json.dumps(body),)
        except Exception as e:
            raise ValidationError(str(e))
        
        res = response.json()
        
        if res.get('error'):
            raise ValidationError(json.dumps(res.get('error')))
        if not res.get('success'):
            _logger.info("=== CRON cron_synchronize_sap_production_order NOT SUCCESS ===")
            return True
        
        data_list = res.get('data', [])
        _logger.info(f"TOTAL DATA aufk: {len(data_list)}")
        
        po_sap = self.env['production.order.sap'].sudo()
        companies = self.env['res.company'].sudo()
        product_template = self.env['product.template'].sudo()
        unit_of_measure = self.env['uom.uom'].sudo()
        for data in data_list:
            po_number = data.get('AUFNR')
            if not po_number:
                continue
            
            order_type = data.get('AUART') or ''
            company_registry = data.get('WERKS') or ''
            if company_registry:
                company_id = companies.search([
                    ('company_registry', '=', company_registry),
                    ('sync_wms', '=', True),
                    ('sync_pm', '=', False),
                ], limit=1)
                if not company_id:
                    continue
            
            product_code = data.get('MATNR') or ''
            if product_code:
                product_id = product_template.search([('default_code', '=', product_code)], limit=1)
                if not product_id:
                    continue
                
            unit = data.get('GMEIN') or ''
            product_uom = False
            if unit.upper() != "KG":
                uom_numerator = float(data.get('UMREZ'))
                uom_denominator = float(data.get('UMREN'))
                ratio = float(uom_numerator) / float(uom_denominator)
                ratio = int(ratio) if ratio.is_integer() else ratio
                uom_name = f"{unit} {ratio}"
                product_uom = unit_of_measure.search([('name', '=', uom_name)], limit=1)
            else:
                product_uom = unit_of_measure.search([('name', '=', 'kg')], limit=1)
            
            raw_start = data.get('GSTRP')
            if raw_start and len(raw_start) == 8:
                start_date = datetime.strptime(raw_start, "%Y%m%d").date()

            raw_finish = data.get('GLTRP')
            if raw_finish and len(raw_finish) == 8:
                finish_date = datetime.strptime(raw_finish, "%Y%m%d").date()
            
            order_qty = float(data.get('GAMNG')) or 0.0
            created_user = data.get('ERNAM') or ''
            teco_status = data.get('TECO_STATUS') or ''
            
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
            }
            
            existing_po_sap = po_sap.search([('po_number', '=', po_number)], limit=1)
            if not existing_po_sap:
                new_po = po_sap.create(vals)
                new_po.message_post(body=f"PO SAP {po_sap} Created from Cron")
                _logger.info(f"PO SAP {po_sap} Created")
            else:
                existing_po_sap.write(vals)
                _logger.info(f"PO {existing_po_sap.po_number} Updated")