from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from collections import defaultdict
from datetime import datetime, timedelta
from html import escape
import requests
import json
import logging
import pytz
_logger = logging.getLogger(__name__)


class PlanMaintenanceWorkOrder(models.Model):
    _name = 'pm.work.order'
    _description = 'PM Work Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'id desc'
    
    name = fields.Char(string="Name", default="New")
    wo_sap = fields.Char(string="Maintenance Order", tracking=True, index=True)
    tagging_id = fields.Many2one(comodel_name='tagging.record', string="Tagging", tracking=True)
    type_mo = fields.Char(string="Type MO", tracking=True)
    company_id = fields.Many2one(comodel_name='res.company', string="Company", tracking=True)
    system_id = fields.Many2one(comodel_name='tagging.system', string="System", tracking=True)
    sub_system_id = fields.Many2one(comodel_name='tagging.subsystem', string="Sub System", tracking=True)
    equipment_id = fields.Many2one(comodel_name='maintenance.equipment', string="Equipment", domain=[('parent_equipment_id', '=', False)], tracking=True)
    sub_equipment_id = fields.Many2one(comodel_name='maintenance.equipment', string="Sub Equipment", domain=[('parent_equipment_id', '!=', False)], tracking=True)
    pm_wo_material_line_ids = fields.One2many('pm.work.order.material.line', 'pm_work_order_id')
    priority = fields.Char(string="Priority", tracking=True)
    date_from = fields.Datetime(string="Date From", tracking=True)
    date_to = fields.Datetime(string="Date To", tracking=True)
    analysis = fields.Text(string="Analysis", tracking=True)
    problem_handling = fields.Text(string="Problem Handling", tracking=True)
    photo_attachment = fields.Binary(string="Photo")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting_sap', 'Process SAP'),
        ('confirm', 'Confirm'),
        ('rejected', 'Rejected'),
        ('canceled', 'Canceled'),
    ], string="State", default='draft', tracking=True, index=True)
    sap_synchronize = fields.Boolean(string="SAP Synchronize", default=False, tracking=True)
    analysis_id = fields.Many2one(comodel_name='pm.analysis', string="Analysis", tracking=True)
    need_desc = fields.Boolean(string="Need Desc?")
    confirm_number = fields.Char(string="No. Konfirmasi", tracking=True)
    pm_wo_jasa_line_ids = fields.One2many('pm.work.order.jasa.line', 'pm_work_order_id')
    description = fields.Text(string="Description")
    material_only = fields.Boolean(string="Material Only", compute='_compute_flag_material')
    jasa_only = fields.Boolean(string="Jasa Only", compute='_compute_flag_jasa')
    preventif_inspection = fields.Boolean(string="Preventif Inspection", default=False)
    start_time = fields.Datetime(string="Planned Start")
    end_time = fields.Datetime(string="Planned End")
    preventif_visible = fields.Boolean(string="Preventif Visible", compute='_compute_flag_preventif_visible', store=True)
    gi_gr_done = fields.Boolean(string="GI/GR Selesai", compute='_compute_gi_gr_done')
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('pm.work.order') or _('New')
        return super().create(vals_list)
    
    @api.depends('pm_wo_material_line_ids')
    def _compute_flag_material(self):
        for rec in self:
            rec.material_only = bool(rec.pm_wo_material_line_ids)

    @api.depends('pm_wo_jasa_line_ids')
    def _compute_flag_jasa(self):
        for rec in self:
            rec.jasa_only = bool(rec.pm_wo_jasa_line_ids)

    @api.depends('pm_wo_material_line_ids.is_gi', 'pm_wo_jasa_line_ids.is_gr')
    def _compute_gi_gr_done(self):
        for rec in self:
            rec.gi_gr_done = (
                all(line.is_gi for line in rec.pm_wo_material_line_ids)
                and all(line.is_gr for line in rec.pm_wo_jasa_line_ids)
            )
                
    @api.depends('start_time', 'preventif_inspection')
    def _compute_flag_preventif_visible(self):
        now_date = self.today_jakarta()
        tz_name = self.env.user.tz or 'Asia/Jakarta'
        user_tz = pytz.timezone(tz_name)
        
        for rec in self:
            if rec.preventif_inspection:
                if rec.start_time:
                    utc_dt = pytz.utc.localize(rec.start_time)
                    local_dt = utc_dt.astimezone(user_tz)
                    start_date = local_dt.date()
                    rec.preventif_visible = (now_date >= start_date)
                else:
                    rec.preventif_visible = False
            else:
                rec.preventif_visible = True
    
    @api.depends('name', 'wo_sap')
    def _compute_display_name(self):
        for rec in self:
            work_order = rec.name if rec.name else "(Empty)"
            wo_sap = rec.wo_sap if rec.wo_sap else "-"
            name = '%s - [%s]' % (work_order, wo_sap)
            rec.display_name = name
    
    def today_jakarta(self):
        tz = pytz.timezone('Asia/Jakarta')
        now_jakarta = datetime.now(tz)
        return now_jakarta.date()
    
    def now_jakarta(self):
        tz = pytz.timezone('Asia/Jakarta')
        return datetime.now(pytz.utc).astimezone(tz)
    
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
    
    def _parse_string_datetime(self, date_str, time_str):
        if not date_str or date_str == '00000000':
            return False
        time_str = time_str if time_str else '000000'
        try:
            local_time = datetime.strptime(date_str + time_str, '%Y%m%d%H%M%S')
            utc_time = local_time - timedelta(hours=7)
            return utc_time
        except ValueError as e:
            _logger.warning(f"Gagal memparsing waktu SAP: {date_str} {time_str}. Error: {e}")
            return False

    def _sync_sap_work_order_lines(self, work_order, rows, company):
        spare_part_model = self.env['tagging.spare_part'].sudo()
        wo_material_line_model = self.env['pm.work.order.material.line'].sudo()
        wo_jasa_line_model = self.env['pm.work.order.jasa.line'].sudo()

        for row in rows:
            has_rsnum = bool((row.get('RSNUM') or '').strip())
            has_banfn = bool((row.get('BANFN') or '').strip())
            is_kzear_x = (row.get('KZEAR') or '').strip() == 'X'
            is_kzabn_x = (row.get('KZABN') or '').strip() == 'X'

            if has_rsnum:
                matnr = row.get('MATNR')
                maktx = row.get('MAKTX')
                qty = float(row.get('ENMNG') or 0.0)

                sparepart = spare_part_model.search([
                    ('active', '=', True),
                    ('sku', '=', matnr),
                    ('company_id', '=', company.id),
                ], limit=1)

                if not sparepart and matnr:
                    sparepart = spare_part_model.create({
                        'name': maktx,
                        'sku': matnr,
                        'company_id': company.id,
                    })

                existing_material = wo_material_line_model.search([
                    ('pm_work_order_id', '=', work_order.id),
                    ('product_sparepart_id', '=', sparepart.id),
                ], limit=1)

                mat_vals = {
                    'pm_work_order_id': work_order.id,
                    'product_sparepart_id': sparepart.id,
                    'product_material': sparepart.sku,
                    'quantity': qty,
                    'gi_doc': (row.get('RSNUM') or '').strip().lstrip('0'),
                    'is_gi': is_kzear_x,
                }

                if not existing_material:
                    wo_material_line_model.create(mat_vals)
                elif self._needs_update(existing_material, mat_vals):
                    existing_material.write(mat_vals)

            if has_banfn:
                banfn = (row.get('BANFN') or '').strip().lstrip('0')
                existing_jasa = wo_jasa_line_model.search([
                    ('pm_work_order_id', '=', work_order.id),
                    ('gr_doc', '=', banfn),
                ], limit=1)

                jasa_vals = {
                    'pm_work_order_id': work_order.id,
                    'material_desc': row.get('TXZ01'),
                    'sku_desc': row.get('SKU'),
                    'gr_doc': banfn,
                    'is_gr': is_kzabn_x,
                }

                if not existing_jasa:
                    wo_jasa_line_model.create(jasa_vals)
                elif self._needs_update(existing_jasa, jasa_vals):
                    existing_jasa.write(jasa_vals)
    
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

    @api.onchange('analysis_id')
    def _onchange_analysis_pm(self):
        for rec in self:
            if rec.analysis_id.need_desc:
                rec.need_desc = True
            else:
                rec.need_desc = False
                
    def action_waiting_sap(self):
        for rec in self:
            if rec.state != 'draft' and not rec.sap_synchronize:
                raise ValidationError(f"Status pada {rec.name} bukan Draft dan SAP Synchronize belum ceklis!")
            if not rec.date_from:
                raise ValidationError("Date From harus diisi!")
            if not rec.date_to:
                raise ValidationError("Date To harus diisi!")
            if not rec.analysis_id:
                raise ValidationError("Analysis harus diisi!")
            if rec.analysis_id and rec.analysis_id.need_desc:
                if not rec.analysis:
                    raise ValidationError("Analysis Desc harus diisi karena membutuhkan Deskripsi!")
            if not rec.problem_handling:
                raise ValidationError("Problem Handling harus diisi!")
            if not rec.photo_attachment:
                raise ValidationError("Photo harus diisi!")
            if rec.date_from and rec.date_to:
                if rec.date_to < rec.date_from:
                    raise ValidationError("Date To tidak boleh kurang dari Date From!")
            rec._check_gi_gr_done()
            rec.write({'state': 'waiting_sap'})

    def _check_gi_gr_done(self):
        self.ensure_one()
        pending_gi = self.pm_wo_material_line_ids.filtered(lambda line: not line.is_gi)
        pending_gr = self.pm_wo_jasa_line_ids.filtered(lambda line: not line.is_gr)
        if not pending_gi and not pending_gr:
            return

        messages = []
        if pending_gi:
            materials = ', '.join(
                line.product_material or line.product_sparepart_id.display_name or '-'
                for line in pending_gi
            )
            messages.append(f"Material yang belum GI: {materials}")
        if pending_gr:
            jasas = ', '.join(
                line.gr_doc or line.material_desc or '-' for line in pending_gr
            )
            messages.append(f"Jasa yang belum GR: {jasas}")

        detail = chr(10).join(messages)
        raise ValidationError(
            f"{self.name} belum bisa disubmit karena masih ada proses SAP "
            f"yang belum selesai.{chr(10)}{detail}"
        )
    
    def action_close(self):
        for rec in self:
            if rec.state == 'waiting_sap':
                rec.write({
                    'state': 'confirm',
                })
                
                if rec.tagging_id:
                    rec.tagging_id.write({
                        'close_start_date': rec.date_from,
                        'close_end_date': rec.date_to,
                        'close_description': rec.analysis_id.name if rec.analysis_id else False,
                        'close_reason': rec.problem_handling,
                        'close_photo': rec.photo_attachment,
                    })
                    rec.tagging_id.message_post(body=f"Close Evidence terpenuhi dari {rec.name}")
                
    def action_cancel(self):
        for rec in self:
            rec.state = 'canceled'
    
    @api.model
    def cron_synhronize_sap_tagging_work_order(self):
        data_list = self._fetch_sap_data(
            config_key='query_tagging_work_order_material_sap',
            cron_name='cron_synhronize_sap_tagging_work_order',
        )
        if not data_list:
            return True

        _logger.info(f"TOTAL DATA cron_synhronize_sap_tagging_work_order: {len(data_list)}")

        pm_wo_model = self.env['pm.work.order'].sudo()
        tagging_model = self.env['tagging.record'].sudo()
        company_model = self.env['res.company'].sudo()
        
        grouped_data = defaultdict(list)
        for data in data_list:
            nomor_wo = (data.get('AUFNR') or '').strip().lstrip('0')
            if not nomor_wo:
                continue
            grouped_data[nomor_wo].append(data)
            
        for nomor_wo, rows in grouped_data.items():
            first = rows[0]
            no_tagging = first.get('FETXT', '')
            type_mo = first.get('AUART')
            priority = first.get('PRIOKX')
            wo_sap = nomor_wo
            werks = first.get('WERKS') or first.get('COMPANY_ID')
            ktext = first.get('KTEXT')
            strmn = first.get('STRMN', '')
            strur = first.get('STRUR', '')
            ltrmn = first.get('LTRMN', '')
            ltrur = first.get('LTRUR', '')
            
            company = company_model.search([('company_registry', '=', werks),('sync_pm', '=', True)], limit=1)
            if not company:
                _logger.warning(f"Company Plant {werks} skipped")
                continue
            
            tagging = tagging_model.search([('name', '=', no_tagging),('company_id', '=', company.id)], limit=1)
            if not tagging:
                _logger.warning(f"Tagging {no_tagging} skipped")
                continue
            
            starttime = self._parse_string_datetime(strmn, strur)
            endtime = self._parse_string_datetime(ltrmn, ltrur)
            if not endtime:
                endtime = starttime
                
            work_order = pm_wo_model.search([('tagging_id', '=', tagging.id),('company_id', '=', company.id)], limit=1)
            vals = {
                'tagging_id': tagging.id,
                'wo_sap': wo_sap,
                'type_mo': type_mo,
                'priority': priority,
                'sap_synchronize': True,
                'system_id': tagging.system_id.id,
                'sub_system_id': tagging.sub_system_id.id,
                'equipment_id': tagging.parent_equipment_id.id,
                'sub_equipment_id': tagging.equipment_id.id,
                'company_id': company.id,
                'description': ktext,
                'start_time': starttime,
                'end_time': endtime,
            }
            
            if not work_order:
                work_order = pm_wo_model.create(vals)
                work_order.message_post(body=f"WORK ORDER {wo_sap} Created from Cron")
                _logger.info(f"WORK ORDER Created {wo_sap}")
            else:
                if self._needs_update(work_order, vals):
                    work_order.write(vals)
                    _logger.info(f"WORK ORDER Updated {wo_sap}")
            
            self._sync_sap_work_order_lines(work_order, rows, company)
            
            if work_order.tagging_id and work_order.tagging_id.status == 'process_sap':
                work_order.tagging_id.write({
                    'status': 'open_wo',
                    'pm_work_order_id': work_order.id,
                })
            
    @api.model
    def cron_synhronize_sap_work_order(self):
        data_list = self._fetch_sap_data(
            config_key='query_work_order_material_sap',
            cron_name='cron_synhronize_sap_work_order',
        )
        if not data_list:
            return True
        
        _logger.info(f"TOTAL DATA cron_synhronize_sap_work_order: {len(data_list)}")
        
        pm_wo_model = self.env['pm.work.order'].sudo()
        equip_model = self.env['maintenance.equipment'].sudo()
        company_model = self.env['res.company'].sudo()
        grouped_data = defaultdict(list)
        
        for row in data_list:
            nomor_wo = (row.get('AUFNR') or '').strip().lstrip('0')
            if nomor_wo:
                grouped_data[nomor_wo].append(row)
            
        for nomor_wo, rows in grouped_data.items():
            first = rows[0]
            type_mo = first.get('AUART')
            priority = first.get('PRIOKX')
            sub_equip = (first.get('EQUNR') or "").lstrip('0')
            company_registry = first.get('WERKS')
            ktext = first.get('KTEXT')
            strmn = first.get('STRMN', '')
            strur = first.get('STRUR', '')
            ltrmn = first.get('LTRMN', '')
            ltrur = first.get('LTRUR', '')
            
            company = company_model.search([('company_registry', '=', company_registry),('sync_pm', '=', True)], limit=1)
            if not company:
                _logger.info(f"Company Plant {company_registry} cron_synhronize_sap_work_order skipped")
                continue
            
            equipment = equip_model.search([('equipment_no', '=', sub_equip),('company_id', '=', company.id)], limit=1)
            if not equipment:
                _logger.info(f"{nomor_wo} Sub Equipment {sub_equip} cron_synhronize_sap_work_order skipped")
                continue
            else:
                if not equipment.parent_equipment_id:
                    equipment_id = equipment.id
                    sub_equipment_id = equip_model.search([('parent_equipment_id', '=', equipment_id)], limit=1).id
                else:
                    equipment_id = equipment.parent_equipment_id.id
                    sub_equipment_id = equipment.id
            
            starttime = self._parse_string_datetime(strmn, strur)
            endtime = self._parse_string_datetime(ltrmn, ltrur)
            if not endtime:
                endtime = starttime
            
            work_order = pm_wo_model.search([('wo_sap', '=', nomor_wo),('company_id', '=', company.id)], limit=1)
            vals = {
                'wo_sap': nomor_wo,
                'type_mo': type_mo,
                'priority': priority,
                'sap_synchronize': True,
                'system_id': equipment.system_id.id,
                'sub_system_id': equipment.sub_system_id.id,
                'equipment_id': equipment_id,
                'sub_equipment_id': sub_equipment_id,
                'company_id': company.id,
                'description': ktext,
                'start_time': starttime,
                'end_time': endtime,
            }
            if not work_order:
                work_order = pm_wo_model.create(vals)
                work_order.message_post(body=f"WORK ORDER {nomor_wo} Created from Cron")
                _logger.info(f"WORK ORDER Created {nomor_wo}")
            else:
                if self._needs_update(work_order, vals):
                    work_order.write(vals)
            
            self._sync_sap_work_order_lines(work_order, rows, company)
    
    @api.model
    def cron_synhronize_sap_preventif_inspection(self):
        data_list = self._fetch_sap_data(
            config_key='query_preventif_inspection_work_order_sap',
            cron_name='cron_synhronize_sap_preventif_inspection',
        )
        if not data_list:
            return True

        _logger.info(f"TOTAL DATA cron_synhronize_sap_preventif_inspection {len(data_list)}")
        
        pm_wo_model = self.env['pm.work.order'].sudo()
        equip_model = self.env['maintenance.equipment'].sudo()
        company_model = self.env['res.company'].sudo()
        grouped_data = defaultdict(list)
        
        for row in data_list:
            nomor_wo = (row.get('AUFNR') or '').strip().lstrip('0')
            if nomor_wo:
                grouped_data[nomor_wo].append(row)
        
        for nomor_wo, rows in grouped_data.items():
            first = rows[0]
            type_mo = first.get('AUART')
            priority = first.get('PRIOKX')
            sub_equip = (first.get('EQUNR') or "").lstrip('0')
            company_registry = first.get('WERKS')
            ktext = first.get('KTEXT')
            nplda = first.get('NPLDA', '')
            strur = first.get('STRUR', '')
            ltrmn = first.get('LTRMN', '')
            ltrur = first.get('LTRUR', '')
            
            company = company_model.search([('company_registry', '=', company_registry),('sync_pm', '=', True)], limit=1)
            if not company:
                _logger.info(f"Company Plant {company_registry} cron_synhronize_sap_preventif_inspection skipped")
                continue
            
            equipment = equip_model.search([('equipment_no', '=', sub_equip),('company_id', '=', company.id)], limit=1)
            if not equipment:
                _logger.info(f"Sub Equipment {sub_equip} cron_synhronize_sap_preventif_inspection skipped")
                continue
            else:
                if not equipment.parent_equipment_id:
                    equipment_id = equipment.id
                    sub_equipment_id = equip_model.search([('parent_equipment_id', '=', equipment_id)], limit=1).id
                else:
                    equipment_id = equipment.parent_equipment_id.id
                    sub_equipment_id = equipment.id
            
            starttime = self._parse_string_datetime(nplda, strur)
            endtime = starttime
            
            wo_preventif = pm_wo_model.search([('wo_sap', '=', nomor_wo),('company_id', '=', company.id)], limit=1)
            vals = {
                'wo_sap': nomor_wo,
                'type_mo': type_mo,
                'priority': priority,
                'sap_synchronize': True,
                'system_id': equipment.system_id.id,
                'sub_system_id': equipment.sub_system_id.id,
                'equipment_id': equipment_id,
                'sub_equipment_id': sub_equipment_id,
                'company_id': company.id,
                'description': ktext,
                'preventif_inspection': True,
                'start_time': starttime,
                'end_time': endtime,
            }
            if not wo_preventif:
                wo_preventif = pm_wo_model.create(vals)
                wo_preventif.message_post(body=f"PREVENTIF WORK ORDER {nomor_wo} Created from Cron")
                _logger.info(f"PREVENTIF WORK ORDER Created {nomor_wo}")
            else:
                if self._needs_update(wo_preventif, vals):
                    wo_preventif.write(vals)
            
            self._sync_sap_work_order_lines(wo_preventif, rows, company)
            
    @api.model
    def cron_synhronize_sap_refurbish_work_order(self):
        data_list = self._fetch_sap_data(
            config_key='query_work_order_refurbish_sap',
            cron_name='cron_synhronize_sap_refurbish_work_order',
        )
        if not data_list:
            return True
        
        _logger.info(f"TOTAL DATA cron_synhronize_sap_refurbish_work_order: {len(data_list)}")
        
        pm_wo_model = self.env['pm.work.order'].sudo()
        equip_model = self.env['maintenance.equipment'].sudo()
        company_model = self.env['res.company'].sudo()
        grouped_data = defaultdict(list)
        
        for row in data_list:
            nomor_wo = (row.get('AUFNR') or '').strip().lstrip('0')
            if nomor_wo:
                grouped_data[nomor_wo].append(row)
            
        for nomor_wo, rows in grouped_data.items():
            first = rows[0]
            type_mo = first.get('AUART')
            priority = first.get('PRIOKX')
            sub_equip = (first.get('EQUNR') or "").lstrip('0')
            company_registry = first.get('WERKS')
            ktext = first.get('KTEXT')
            strmn = first.get('STRMN', '')
            strur = first.get('STRUR', '')
            ltrmn = first.get('LTRMN', '')
            ltrur = first.get('LTRUR', '')
            
            company = company_model.search([('company_registry', '=', company_registry),('sync_pm', '=', True)], limit=1)
            if not company:
                _logger.info(f"Company Plant {company_registry} cron_synhronize_sap_refurbish_work_order skipped")
                continue
            
            # equipment = equip_model.search([('equipment_no', '=', sub_equip),('company_id', '=', company.id)], limit=1)
            # if not equipment:
            #     _logger.info(f"{nomor_wo} Sub Equipment {sub_equip} cron_synhronize_sap_refurbish_work_order skipped")
            #     continue
            # else:
            #     if not equipment.parent_equipment_id:
            #         equipment_id = equipment.id
            #         sub_equipment_id = equip_model.search([('parent_equipment_id', '=', equipment_id)], limit=1).id
            #     else:
            #         equipment_id = equipment.parent_equipment_id.id
            #         sub_equipment_id = equipment.id
            
            starttime = self._parse_string_datetime(strmn, strur)
            endtime = self._parse_string_datetime(ltrmn, ltrur)
            if not endtime:
                endtime = starttime
            
            work_order = pm_wo_model.search([('wo_sap', '=', nomor_wo),('company_id', '=', company.id)], limit=1)
            vals = {
                'wo_sap': nomor_wo,
                'type_mo': type_mo,
                'priority': priority,
                'sap_synchronize': True,
                # 'system_id': equipment.system_id.id,
                # 'sub_system_id': equipment.sub_system_id.id,
                # 'equipment_id': equipment_id,
                # 'sub_equipment_id': sub_equipment_id,
                'company_id': company.id,
                'description': ktext,
                'start_time': starttime,
                'end_time': endtime,
            }
            if not work_order:
                work_order = pm_wo_model.create(vals)
                work_order.message_post(body=f"WORK ORDER REFURBISH {nomor_wo} Created from Cron")
                _logger.info(f"WORK ORDER REFURBISH Created {nomor_wo}")
            else:
                if self._needs_update(work_order, vals):
                    work_order.write(vals)
            
            self._sync_sap_work_order_lines(work_order, rows, company)
                    
    @api.model
    def cron_reminder_wo_draft(self):
        self = self.sudo()
        draft_wos = self.sudo().search([('state', '=', 'draft')])
        if not draft_wos:
            _logger.info("cron_reminder_wo_draft Tidak Ditemukan, skipped!")
            return True

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        wos_by_dept = defaultdict(list)
        for wo in draft_wos:
            if wo.tagging_id and wo.tagging_id.department_id:
                wos_by_dept[wo.tagging_id.department_id].append(wo)

        mails = []
        for dept, wos in wos_by_dept.items():
            emails = []
            for pic in dept.pic_ids:
                if pic.email:
                    emails.append(pic.email)
            
            emails = list(set(emails))
            if not emails:
                _logger.info(f"cron_reminder_wo_draft Email tidak ada untuk Dept {dept.name}, skipped!")
                continue

            rows = ""
            for i, wo in enumerate(wos, start=1):
                open_url = f"{base_url}/web#id={wo.id}&model=pm.work.order&view_type=form"
                wo_name = escape(wo.wo_sap or wo.name or '-')
                status = escape(dict(self._fields['state'].selection).get(wo.state, '-'))
                type_mo = escape(wo.type_mo or '-')
                system = escape(wo.system_id.name or '-')
                sub_system = escape(wo.sub_system_id.name or '-')
                created_on = str(wo.create_date)[:19] if wo.create_date else '-' 
                
                rows += f"""
                    <tr>
                        <td style="padding: 8px; text-align: center;">{i}</td>
                        <td style="padding: 8px;">
                            <a href="{open_url}" style="color: #007bff; text-decoration: none; font-weight: bold;">
                                {wo_name}
                            </a>
                        </td>
                        <td style="padding: 8px;">{status}</td>
                        <td style="padding: 8px;">{type_mo}</td>
                        <td style="padding: 8px;">{system}</td>
                        <td style="padding: 8px;">{sub_system}</td>
                        <td style="padding: 8px;">{created_on}</td>
                    </tr>
                """
                
            body_html = f"""
                <div style="font-family: Arial, sans-serif; font-size: 13px; color: #333333;">
                    <p>Dear Team,</p>
                    <p>Berikut adalah Maintenance Order yang belum selesai :</p>
                    
                    <table border="1" style="width: 100%; border-collapse: collapse; margin-top: 15px;">
                        <thead>
                            <tr style="background-color: #f2f2f2; text-align: left;">
                                <th style="padding: 8px;">No</th>
                                <th style="padding: 8px;">Maintenance Order</th>
                                <th style="padding: 8px;">Status</th>
                                <th style="padding: 8px;">Type MO</th>
                                <th style="padding: 8px;">System</th>
                                <th style="padding: 8px;">Sub System</th>
                                <th style="padding: 8px;">Created On</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows}
                        </tbody>
                    </table>
                    <br/>
                    <p>Terima kasih.</p>
                </div>
            """
            
            subject = f"[REMINDER] Draft Maintenance Order ({len(wos)} items)"
            mail_values = {
                "subject": subject,
                "body_html": body_html,
                "email_to": ",".join(emails),
                "email_from": "noreply-ops@cpp.co.id",
            }
            mails.append(mail_values)

        if mails:
            self.env['mail.mail'].sudo().create(mails)

        return True