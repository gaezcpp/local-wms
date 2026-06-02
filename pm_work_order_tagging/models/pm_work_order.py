from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from collections import defaultdict
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
    photo_attachment = fields.Binary(string="Photo")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting_sap', 'Waiting SAP'),
        ('closed', 'Closed'),
        ('rejected', 'Rejected'),
        ('canceled', 'Canceled'),
    ], string="State", default='draft')
    sap_synchronize = fields.Boolean(string="SAP Synchronize", default=False, tracking=True)
    analysis_id = fields.Many2one(comodel_name='pm.analysis', string="Analysis", tracking=True)
    need_desc = fields.Boolean(string="Need Desc?")
    confirm_number = fields.Char(string="No. Konfirmasi", tracking=True)
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('pm.work.order') or _('New')
        return super().create(vals_list)
    
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
    def cron_synchronize_sap_work_order_material(self):
        icp = self.env['ir.config_parameter'].sudo()

        x_i_api_key = icp.get_param('x_i_api_key')
        ip_sap_rfc = icp.get_param('ip_sap_rfc')
        query_work_order_material_sap = icp.get_param('query_work_order_material_sap')

        if not x_i_api_key:
            x_i_api_key = icp.get_param('x_i_api_key_tagging')
        if not ip_sap_rfc:
            ip_sap_rfc = icp.get_param('ip_sap_rfc_tagging')
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

            materials_to_add = {}
            materials_to_delete = []
            for rec in records:
                sku = rec.get('MATNR')
                qty = float(rec.get('BDMNG') or 0.0)
                bwart = rec.get('BWART')

                if not sku:
                    continue
                
                if bwart == 'Z62':
                    materials_to_delete.append(sku)
                elif bwart == 'Z61':
                    materials_to_add[sku] = qty

            if materials_to_delete:
                lines_to_unlink = work_order.pm_wo_material_line_ids.filtered(
                    lambda l: l.product_sparepart_id.sku in materials_to_delete
                )
                if lines_to_unlink:
                    lines_to_unlink.unlink()
                    
            existing_lines = {
                line.product_sparepart_id.sku: line
                for line in work_order.pm_wo_material_line_ids
                if line.product_sparepart_id and line.product_sparepart_id.sku
            }

            sequence = len(work_order.pm_wo_material_line_ids)
            create_vals = []

            for sku, qty in materials_to_add.items():
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
                
    @api.onchange('analysis_id')
    def _onchange_analysis_pm(self):
        for rec in self:
            if rec.analysis_id.need_desc:
                rec.need_desc = True
            else:
                rec.need_desc = False
    
    def _validation_per_state(self):
        for rec in self:
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
                
    def action_waiting_sap(self):
        for rec in self:
            if rec.state == 'draft' and rec.sap_synchronize:
                rec.state = 'waiting_sap'
            else:
                raise ValidationError(f"Status pada {rec.name} bukan Draft dan SAP Synchronize belum ceklis!")
    
    def action_close(self):
        for rec in self:
            if rec.state == 'waiting_sap':
                rec.write({
                    'state': 'closed',
                    'end_date': fields.Datetime.now(),
                })
                
    def action_cancel(self):
        for rec in self:
            rec.state = 'canceled'
            
    @api.model
    def cron_synchronize_sap_preventif_work_order(self):
        icp = self.env['ir.config_parameter'].sudo()
        x_i_api_key = icp.get_param('x_i_api_key')
        ip_sap_rfc = icp.get_param('ip_sap_rfc')
        query_preventif_work_order_material_sap = icp.get_param('query_preventif_work_order_material_sap')

        if not x_i_api_key:
            x_i_api_key = icp.get_param('x_i_api_key_tagging')
        if not ip_sap_rfc:
            ip_sap_rfc = icp.get_param('ip_sap_rfc_tagging')
        if not query_preventif_work_order_material_sap:
            raise ValidationError("query_preventif_work_order_material_sap belum disetting!")

        headers = {
            "x-i-api-key": str(x_i_api_key),
            "Content-Type": "application/json"
        }

        url = f"{str(ip_sap_rfc)}/api/v1/zfm-query-data"
        body = {
            "I_QUERY": str(query_preventif_work_order_material_sap),
            "I_MOD": "CRON cron_synchronize_sap_preventif_work_order"
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
            _logger.info(f"cron_synchronize_sap_preventif_work_order Not Success {res}")
            return True
        
        data_list = res.get('data', [])
        if not data_list:
            return True
        
        _logger.info(f"TOTAL DATA PREVENTIF {len(data_list)}")
        
        pm_wo_model = self.env['pm.work.order'].sudo()
        pm_wo_line_model = self.env['pm.work.order.material.line'].sudo()
        equip_model = self.env['maintenance.equipment'].sudo()
        company_model = self.env['res.company'].sudo()
        grouped_data = defaultdict(list)
        
        for row in data_list:
            nomor_wo = row.get('AUFNR')
            if nomor_wo:
                grouped_data[nomor_wo].append(row)
        
        for nomor_wo, rows in grouped_data.items():
            first = rows[0]
            type_mo = first.get('AUART')
            priority = first.get('PRIOKX')
            sub_system = first.get('TPLNR')
            sub_equip = (first.get('EQUNR') or "").lstrip('0')
            company_registry = first.get('WERKS')
            
            company = company_model.search([('company_registry', '=', company_registry),('sync_pm', '=', True)], limit=1)
            if not company:
                _logger.info(f"Company Plant {company_registry} cron_synchronize_sap_preventif_work_order skipped")
                continue
            
            equipment = equip_model.search([('equipment_no', '=', sub_equip),('company_id', '=', company.id)], limit=1)
            if not equipment:
                _logger.info(f"Sub Equipment {sub_equip} cron_synchronize_sap_preventif_work_order skipped")
                continue
            
            wo_preventif = pm_wo_model.search([
                ('wo_sap', '=', nomor_wo),
                ('company_id', '=', company.id),
            ], limit=1)
            
            vals = {
                'wo_sap': nomor_wo,
                'type_mo': type_mo,
                'maintenance_type': 'PREVENTIF',
                'priority': priority,
                'sap_synchronize': True,
                'system_id': equipment.system_id.id,
                'sub_system_id': equipment.sub_system_id.id,
                'equipment_id': equipment.parent_equipment_id.id,
                'sub_equipment_id': equipment.id,
                'company_id': company.id,
            }
            
            if not wo_preventif:
                wo_preventif = pm_wo_model.create(vals)
                wo_preventif.message_post(body=f"PREVENTIF WORK ORDER {nomor_wo} Created from Cron")
                _logger.info(f"PREVENTIF WORK ORDER Created {nomor_wo}")
            else:
                if self._needs_update(wo_preventif, vals):
                    wo_preventif.write(vals)