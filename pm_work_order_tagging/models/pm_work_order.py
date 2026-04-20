from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import requests
import json
import logging
_logger = logging.getLogger(__name__)


class PlanMaintenanceWorkOrder(models.Model):
    _name = 'pm.work.order'
    _description = 'PM Work Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    
    name = fields.Char(string="Name", default="New")
    wo_sap = fields.Char(string="Work Order SAP", tracking=True)
    tagging_id = fields.Many2one(comodel_name='tagging.record', string="Tagging", tracking=True)
    type_mo = fields.Char(string="Type MO", tracking=True)
    company_id = fields.Many2one(comodel_name='res.company', string="Company", tracking=True)
    system_id = fields.Many2one(comodel_name='tagging.system', string="System", tracking=True)
    sub_system_id = fields.Many2one(comodel_name='tagging.subsystem', string="Sub System", tracking=True)
    equipment_id = fields.Many2one(comodel_name='maintenance.equipment', string="Equipment", domain=[('parent_equipment_id', '=', False)], tracking=True)
    sub_equipment_id = fields.Many2one(comodel_name='maintenance.equipment', string="Sub Equipment", domain=[('parent_equipment_id', '!=', False)], tracking=True)
    pm_wo_material_line_ids = fields.One2many('pm.work.order.material.line', 'pm_work_order_id')
    maintenance_type = fields.Selection([
        ('CORRECTIVE', 'CORRECTIVE'),
        ('PREVENTIF', 'PREVENTIF'),
    ], string="Maintenance Type", default=False, tracking=True)
    priority = fields.Char(string="Priority", tracking=True)
    date_from = fields.Datetime(string="Date From", tracking=True)
    date_to = fields.Datetime(string="Date To", tracking=True)
    analysis = fields.Text(string="Analysis", tracking=True)
    problem_handling = fields.Text(string="Problem Handling", tracking=True)
    photo_attachment = fields.Binary(string="Photo", tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting_sap', 'Waiting SAP'),
        ('closed', 'Closed'),
        ('rejected', 'Rejected'),
    ], string="State", default='draft')
    sap_synchronize = fields.Boolean(string="SAP Synchronize", default=False, tracking=True)
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('pm.work.order') or _('New')
        return super().create(vals_list)
    
    @api.model
    def cron_synchronize_sap_work_order_material(self):
        icp = self.env['ir.config_parameter'].sudo()

        x_i_api_key = icp.get_param('x_i_api_key')
        ip_sap_rfc = icp.get_param('ip_sap_rfc')
        query_work_order_material_sap = icp.get_param('query_work_order_material_sap')

        if not x_i_api_key:
            x_i_api_key = icp.get_param('x_i_api_key_tagging')
            # raise ValidationError("x_i_api_key belum disetting!")
        if not ip_sap_rfc:
            ip_sap_rfc = icp.get_param('ip_sap_rfc_tagging')
            # raise ValidationError("ip_sap_rfc belum disetting!")
        if not query_work_order_material_sap:
            raise ValidationError("query_work_order_material_sap belum disetting!")

        headers = {
            "x-i-api-key": str(x_i_api_key),
            "Content-Type": "application/json"
        }

        url = f"{str(ip_sap_rfc)}/api/v1/zfm-query-data"
        body = {
            "I_QUERY": str(query_work_order_material_sap),
            "I_MOD": "CRON cron_synchronize_sap_work_order_material"
        }

        try:
            response = requests.post(url=url, headers=headers, data=json.dumps(body))
            response.raise_for_status()
        except Exception as e:
            raise ValidationError(str(e))

        res = response.json()

        if res.get('error'):
            raise ValidationError(json.dumps(res.get('error')))

        if not res.get('success'):
            return True

        data_list = res.get('data', [])

        pm_wo_model = self.env['pm.work.order'].sudo()
        spare_part_model = self.env['tagging.spare_part'].sudo()
        wo_material_line_model = self.env['pm.work.order.material.line'].sudo()

        grouped = {}
        for data in data_list:
            no_tagging = (data.get('QMTXT') or "").strip()
            if not no_tagging:
                continue
            grouped.setdefault(no_tagging, []).append(data)

        for no_tagging, records in grouped.items():
            wo_name = (records[0].get('AUFNR') or "").lstrip('0')
            type_mo = records[0].get('AUART')
            priority = records[0].get('PRIOKX')

            if not wo_name:
                continue

            work_order = pm_wo_model.search([('tagging_id.name', '=', no_tagging)], limit=1)
            if not work_order:
                continue

            work_order.write({
                'wo_sap': wo_name,
                'type_mo': type_mo,
                'priority': priority,
                'sap_synchronize': True,
            })

            unique_materials = {}
            for rec in records:
                sku = rec.get('MATNR')
                qty = float(rec.get('BDMNG') or 0.0)
                if not sku:
                    continue
                unique_materials[sku] = qty

            existing_lines = {
                line.product_sparepart_id.sku: line
                for line in work_order.pm_wo_material_line_ids
                if line.product_sparepart_id and line.product_sparepart_id.sku
            }

            sequence = len(work_order.pm_wo_material_line_ids)

            create_vals = []
            for sku, qty in unique_materials.items():
                product = spare_part_model.search([('sku', '=', sku)], limit=1)
                if not product:
                    continue

                if sku in existing_lines:
                    existing_lines[sku].write({
                        'product_material': product.sku,
                        'quantity': qty,
                    })
                else:
                    sequence += 1
                    create_vals.append({
                        'pm_work_order_id': work_order.id,
                        'sequence': sequence,
                        'product_sparepart_id': product.id,
                        'product_material': product.sku,
                        'quantity': qty,
                    })

            if create_vals:
                wo_material_line_model.create(create_vals)
    
    def action_close(self):
        for rec in self:
            if rec.state == 'draft' and not rec.type_mo:
                if rec.date_from:
                    raise ValidationError("Tidak bisa melakukan pengisian Date From jika status selain draft dan Type MO belum terisi!")
                if rec.date_to:
                    raise ValidationError("Tidak bisa melakukan pengisian Date To jika status selain draft dan Type MO belum terisi!")
                if rec.analysis:
                    raise ValidationError("Tidak bisa melakukan pengisian Analysis jika status selain draft dan Type MO belum terisi!")
                if rec.problem_handling:
                    raise ValidationError("Tidak bisa melakukan pengisian Problem Handling jika status selain draft dan Type MO belum terisi!")
                if rec.photo_attachment:
                    raise ValidationError("Tidak bisa melakukan pengisian Photo jika status selain draft dan Type MO belum terisi!")
                
                rec.state = 'closed'