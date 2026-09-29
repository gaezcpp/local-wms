from odoo import _, api, fields, models, tools
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
    active = fields.Boolean(string="Active", default=True)
    maintenance_plan_number = fields.Char(string="Maintenance Plan")
    is_maintenance_plan = fields.Boolean(string="Is Plan?", default=False)
    description_planning = fields.Text(string="Description Planning")
    creation_email_sent = fields.Boolean(string="Creation Email Sent", default=False, copy=False, readonly=True)
    calendar_display_name = fields.Char(related='sub_system_id.name', string="Calendar Display Name")
    confirm_email_sent = fields.Boolean(string="Confirm Email Sent", default=False, copy=False, readonly=True)
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('pm.work.order') or _('New')
        records = super().create(vals_list)
        records._send_creation_email_to_department()
        return records

    def write(self, vals):
        result = super().write(vals)
        if {'wo_sap', 'sap_synchronize', 'is_maintenance_plan', 'tagging_id'} & vals.keys():
            self._send_creation_email_to_department()
        return result

    @api.model
    def cron_queue_confirm_emails(self):
        template = self.env.ref('pm_work_order_tagging.mail_template_pm_technical_report_submitted')
        records = self.sudo().with_context(active_test=False)
        last_id = 0
        while batch := records.search([
            ('id', '>', last_id),
            ('state', '=', 'confirm'),
            ('confirm_email_sent', '=', False),
        ], order='id', limit=100):
            last_id = batch[-1].id
            batch = batch.try_lock_for_update(allow_referencing=True)
            batch.invalidate_recordset(['state', 'confirm_email_sent'])
            batch = batch.filtered(
                lambda work_order: work_order.state == 'confirm'
                and not work_order.confirm_email_sent,
            )
            if not batch:
                continue

            departments = self.env['tagging.department'].sudo().search([
                ('active', '=', True),
                ('company_id', 'in', batch.company_id.ids),
                ('department_type', '=', 'planner'),
            ])
            pics = departments.mapped('pic_ids').filtered('active')
            pics |= self.env['tagging.pic'].sudo().search([
                ('active', '=', True),
                ('department_ids', 'in', departments.ids),
            ])
            recipients_by_company = {}
            for company in batch.company_id:
                company_departments = departments.filtered(lambda department: department.company_id == company)
                company_pics = pics.filtered(
                    lambda pic: pic.department_id in company_departments
                    or bool(pic.department_ids & company_departments),
                )
                emails = sorted(set(tools.email_normalize_all(
                    ','.join(company_pics.mapped('email')),
                )))
                if emails:
                    recipients_by_company[company.id] = ','.join(emails)

            queue_batch = batch.filtered(
                lambda work_order: work_order.company_id.id
                in recipients_by_company,
            )
            missing_recipient_batch = batch - queue_batch
            if missing_recipient_batch:
                _logger.warning(
                    "PM confirmation email pending: planner recipient not found "
                    "for work order IDs %s",
                    missing_recipient_batch.ids,
                )
            if not queue_batch:
                continue

            try:
                with self.env.cr.savepoint():
                    rendered = template.sudo()._generate_template(
                        queue_batch.ids,
                        (
                            'auto_delete',
                            'body_html',
                            'email_cc',
                            'email_from',
                            'mail_server_id',
                            'reply_to',
                            'scheduled_date',
                            'subject',
                        ),
                    )
                    mails = []
                    for work_order in queue_batch:
                        values = rendered[work_order.id]
                        values.update({
                            'auto_delete': False,
                            'body': values['body_html'],
                            'email_to': recipients_by_company[
                                work_order.company_id.id
                            ],
                            'model': False,
                            'res_id': False,
                        })
                        if not values.get('email_from'):
                            values.pop('email_from', None)
                        mails.append(values)

                    created_mails = self.env['mail.mail'].sudo().create(mails)
                    if len(created_mails) != len(queue_batch):
                        message = ("Not all PM confirmation emails could be queued")
                        raise ValidationError(message)
                    queue_batch.write({'confirm_email_sent': True})
            except Exception:
                _logger.exception("Failed to queue PM confirmation emails for work order IDs %s", batch.ids)
        return True

    def _send_creation_email_to_department(self):
        template = self.env.ref('pm_work_order_tagging.mail_template_work_order_created')
        if not template:
            _logger.warning("Work order creation email template not found")
            return False

        sent = False
        for work_order in self.filtered(
            lambda wo: wo.wo_sap
            and wo.sap_synchronize
            and not wo.is_maintenance_plan
            and not wo.creation_email_sent
        ):
            tagging = work_order.tagging_id
            department = tagging.department_id
            if not department and work_order.company_id:
                departments = self.env['tagging.department'].sudo().search([
                    ('company_id', '=', work_order.company_id.id),
                    ('active', '=', True),
                    ('name', '=ilike', 'Maintenance%'),
                ], limit=2)
                if len(departments) == 1:
                    department = departments
            if not department:
                _logger.info("Work order creation email skipped for %s: department not found", work_order.wo_sap)
                continue
            if (
                not work_order.company_id
                or department.company_id != work_order.company_id
                or (tagging and tagging.company_id != work_order.company_id)
            ):
                _logger.warning("Work order creation email skipped for %s: company mismatch", work_order.wo_sap)
                continue

            pics = department.pic_ids.filtered('active') | self.env['tagging.pic'].sudo().search([
                ('department_ids', 'in', department.id),
                ('active', '=', True),
            ])
            emails = list(dict.fromkeys(
                email.strip()
                for email in pics.mapped('email')
                if email and email.strip()
            ))
            if not emails:
                _logger.info("Work order creation email skipped for %s: recipient not found", work_order.wo_sap)
                continue

            cc_emails = list(dict.fromkeys(
                email.strip()
                for email in pics.mapped('cc')
                if email and email.strip()
            ))
            email_values = {
                'auto_delete': False,
                'email_to': ','.join(emails),
                'model': False,
                'res_id': False,
            }
            if cc_emails:
                email_values['email_cc'] = ','.join(cc_emails)
            try:
                with self.env.cr.savepoint():
                    template.sudo().send_mail(work_order.id, email_values=email_values)
            except Exception:
                _logger.exception("Failed to queue work order creation email for %s", work_order.wo_sap)
                continue
            work_order.creation_email_sent = True
            sent = True
        return sent
    
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

        active_item_numbers = {
            (row.get('RSPOS') or '').strip()
            for row in rows
            if (row.get('RSNUM') or '').strip()
            and not (
                not (row.get('KZEAR') or '').strip()
                and (row.get('XLOEK') or '').strip() == 'X'
            )
            and (row.get('RSPOS') or '').strip()
        }
        deleted_item_numbers = {
            (row.get('RSPOS') or '').strip()
            for row in rows
            if not (row.get('KZEAR') or '').strip()
            and (row.get('XLOEK') or '').strip() == 'X'
            and (row.get('RSPOS') or '').strip()
        } - active_item_numbers
        for row in rows:
            if (
                not (row.get('KZEAR') or '').strip()
                and (row.get('XLOEK') or '').strip() == 'X'
                and not (row.get('RSPOS') or '').strip()
            ):
                _logger.warning(
                    "SAP material deletion skipped: RSPOS empty for WO %s, RSNUM %s",
                    work_order.wo_sap or work_order.name,
                    (row.get('RSNUM') or '').strip(),
                )
        if deleted_item_numbers:
            wo_material_line_model.search([
                ('pm_work_order_id', '=', work_order.id),
                ('item_number', 'in', list(deleted_item_numbers)),
            ]).unlink()

        deleted_jasa_docs = {
            (row.get('BANFN') or '').strip().lstrip('0')
            for row in rows
            if (row.get('BANFN') or '').strip().lstrip('0')
            and (row.get('LOEKZ') or '').strip() == 'X'
            and (row.get('FRGKZ') or '').strip() in ('', 'X')
        }
        if deleted_jasa_docs:
            wo_jasa_line_model.search([
                ('pm_work_order_id', '=', work_order.id),
                ('gr_doc', 'in', list(deleted_jasa_docs)),
            ]).unlink()

        for row in rows:
            has_rsnum = bool((row.get('RSNUM') or '').strip())
            has_banfn = bool((row.get('BANFN') or '').strip())
            kzear = (row.get('KZEAR') or '').strip()
            is_kzear_x = kzear == 'X'
            is_kzabn_x = (row.get('KZABN') or '').strip() == 'X'
            is_deleted_material = (
                not kzear and (row.get('XLOEK') or '').strip() == 'X'
            )
            item_number = (row.get('RSPOS') or '').strip()
            valuation = (row.get('CHARG') or '').strip()
            material_detail = (row.get('POTX1') or '').strip()

            if has_rsnum and not is_deleted_material:
                if not item_number:
                    _logger.warning(
                        "SAP material skipped: RSPOS empty for WO %s, RSNUM %s",
                        work_order.wo_sap or work_order.name,
                        (row.get('RSNUM') or '').strip(),
                    )
                    has_rsnum = False

            if has_rsnum and not is_deleted_material:
                matnr = (row.get('MATNR') or '').strip()
                maktx = row.get('MAKTX')
                qty = float(row.get('BDMNG') or 0.0)
                if not qty:
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
                    ('item_number', '=', item_number),
                ], limit=1)

                mat_vals = {
                    'pm_work_order_id': work_order.id,
                    'item_number': item_number,
                    'product_sparepart_id': sparepart.id,
                    'product_material': sparepart.sku,
                    'quantity': qty,
                    'gi_doc': (row.get('RSNUM') or '').strip().lstrip('0'),
                    'is_gi': is_kzear_x,
                    'valuation': valuation,
                    'material_detail': material_detail,
                }

                if not existing_material:
                    wo_material_line_model.create(mat_vals)
                elif self._needs_update(existing_material, mat_vals):
                    existing_material.write(mat_vals)

            if has_banfn:
                banfn = (row.get('BANFN') or '').strip().lstrip('0')
                if not banfn or banfn in deleted_jasa_docs:
                    continue
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
            werks = str(
                data.get('WERKS') or data.get('COMPANY_ID') or ''
            ).strip()
            if nomor_wo and werks:
                grouped_data[(werks, nomor_wo)].append(data)
            
        for (werks, nomor_wo), rows in grouped_data.items():
            first = rows[0]
            no_tagging = first.get('FETXT', '')
            type_mo = first.get('AUART')
            priority = first.get('PRIOKX')
            wo_sap = nomor_wo
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
            work_order._send_creation_email_to_department()
            
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
            company_registry = str(row.get('WERKS') or '').strip()
            if nomor_wo and company_registry:
                grouped_data[(company_registry, nomor_wo)].append(row)
            
        for (company_registry, nomor_wo), rows in grouped_data.items():
            first = rows[0]
            type_mo = first.get('AUART')
            priority = first.get('PRIOKX')
            sub_equip = (first.get('EQUNR') or "").lstrip('0')
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
            work_order._send_creation_email_to_department()
    
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
            nomor_wo = str(row.get('AUFNR') or '').strip().lstrip('0')
            company_registry = str(row.get('WERKS') or '').strip()
            if nomor_wo and company_registry:
                grouped_data[(company_registry, nomor_wo)].append(row)

        companies = company_model.search([
            ('company_registry', 'in', list({key[0] for key in grouped_data})),
            ('sync_pm', '=', True),
        ])
        companies_by_registry = {
            company.company_registry: company for company in companies
        }
        equipment_numbers = {
            str(rows[0].get('EQUNR') or '').strip().lstrip('0')
            for rows in grouped_data.values()
        }
        equipments = equip_model.search([
            ('equipment_no', 'in', list(equipment_numbers)),
            ('company_id', 'in', companies.ids),
        ])
        equipments_by_key = {
            (equipment.company_id.id, equipment.equipment_no): equipment
            for equipment in equipments
        }
        parent_equipments = equipments.filtered(
            lambda equipment: not equipment.parent_equipment_id
        )
        children = equip_model.search([
            ('parent_equipment_id', 'in', parent_equipments.ids),
        ], order='id')
        children_by_parent = {}
        for child in children:
            children_by_parent.setdefault(child.parent_equipment_id.id, child)

        existing_work_orders = pm_wo_model.search([
            ('company_id', 'in', companies.ids),
            ('wo_sap', 'in', list({key[1] for key in grouped_data})),
        ])
        work_orders_by_sap = defaultdict(lambda: pm_wo_model)
        for work_order in existing_work_orders:
            work_orders_by_sap[
                (work_order.company_id.id, work_order.wo_sap)
            ] |= work_order

        planning_candidates = pm_wo_model.search([
            ('company_id', 'in', companies.ids),
            ('is_maintenance_plan', '=', True),
            ('wo_sap', '=', False),
        ])
        planning_by_key = defaultdict(lambda: pm_wo_model)
        for work_order in planning_candidates:
            planning_by_key[
                (
                    work_order.company_id.id,
                    work_order.start_time,
                    work_order.equipment_id.id,
                    work_order.sub_equipment_id.id,
                )
            ] |= work_order

        for (company_registry, nomor_wo), rows in grouped_data.items():
            first = rows[0]
            company = companies_by_registry.get(company_registry)
            if not company:
                _logger.info(
                    "Company Plant %s cron_synhronize_sap_preventif_inspection skipped",
                    company_registry,
                )
                continue

            sub_equip = str(first.get('EQUNR') or '').strip().lstrip('0')
            equipment = equipments_by_key.get((company.id, sub_equip))
            if not equipment:
                _logger.info(
                    "Sub Equipment %s cron_synhronize_sap_preventif_inspection skipped",
                    sub_equip,
                )
                continue

            if equipment.parent_equipment_id:
                equipment_id = equipment.parent_equipment_id.id
                sub_equipment_id = equipment.id
            else:
                equipment_id = equipment.id
                sub_equipment_id = children_by_parent.get(
                    equipment.id, equip_model,
                ).id

            starttime = self._parse_string_datetime(
                str(first.get('NPLDA') or '').strip(),
                str(first.get('STRUR') or '').strip(),
            )
            wo_preventif = work_orders_by_sap[(company.id, nomor_wo)]
            if len(wo_preventif) > 1:
                _logger.error(
                    "Duplicate preventive work orders for company %s and SAP WO %s: %s; skipped",
                    company.display_name,
                    nomor_wo,
                    wo_preventif.ids,
                )
                continue
            if not wo_preventif:
                planning_key = (
                    company.id, starttime, equipment_id, sub_equipment_id,
                )
                candidates = planning_by_key[planning_key]
                if len(candidates) > 1:
                    _logger.error(
                        "Multiple planning work orders match SAP WO %s: %s; skipped",
                        nomor_wo,
                        candidates.ids,
                    )
                    continue
                wo_preventif = candidates
                if wo_preventif:
                    planning_by_key[planning_key] = pm_wo_model

            vals = {
                'wo_sap': nomor_wo,
                'type_mo': first.get('AUART'),
                'priority': first.get('PRIOKX'),
                'sap_synchronize': True,
                'system_id': equipment.system_id.id,
                'sub_system_id': equipment.sub_system_id.id,
                'equipment_id': equipment_id,
                'sub_equipment_id': sub_equipment_id,
                'company_id': company.id,
                'description': first.get('KTEXT'),
                'preventif_inspection': True,
                'start_time': starttime,
                'end_time': starttime,
            }
            if not wo_preventif:
                wo_preventif = pm_wo_model.create(vals)
                work_orders_by_sap[(company.id, nomor_wo)] = wo_preventif
                wo_preventif.message_post(body=f"PREVENTIF WORK ORDER {nomor_wo} Created from Cron")
                _logger.info("PREVENTIF WORK ORDER Created %s", nomor_wo)
            elif self._needs_update(wo_preventif, vals):
                wo_preventif.write(vals)
                work_orders_by_sap[(company.id, nomor_wo)] = wo_preventif

            self._sync_sap_work_order_lines(wo_preventif, rows, company)
            wo_preventif._send_creation_email_to_department()
            
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
        company_model = self.env['res.company'].sudo()
        grouped_data = defaultdict(list)
        
        for row in data_list:
            nomor_wo = (row.get('AUFNR') or '').strip().lstrip('0')
            company_registry = str(row.get('WERKS') or '').strip()
            if nomor_wo and company_registry:
                grouped_data[(company_registry, nomor_wo)].append(row)
            
        for (company_registry, nomor_wo), rows in grouped_data.items():
            first = rows[0]
            type_mo = first.get('AUART')
            priority = first.get('PRIOKX')
            ktext = first.get('KTEXT')
            strmn = first.get('STRMN', '')
            strur = first.get('STRUR', '')
            ltrmn = first.get('LTRMN', '')
            ltrur = first.get('LTRUR', '')
            
            company = company_model.search([('company_registry', '=', company_registry),('sync_pm', '=', True)], limit=1)
            if not company:
                _logger.info(f"Company Plant {company_registry} cron_synhronize_sap_refurbish_work_order skipped")
                continue
            
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
            work_order._send_creation_email_to_department()

    @api.model
    def cron_synhronize_sap_preventif_planning_wo(self):
        data_list = self._fetch_sap_data(
            config_key='query_preventif_planning_work_order_sap',
            cron_name='cron_synhronize_sap_preventif_planning_wo',
        )
        _logger.info(f"TOTAL DATA cron_synhronize_sap_preventif_planning_wo {len(data_list)}")

        pm_wo_model = self.env['pm.work.order'].sudo()
        company_model = self.env['res.company'].sudo()
        equip_model = self.env['maintenance.equipment'].sudo()
        today = self.today_jakarta()
        delete_before = today - timedelta(days=2)

        parsed_rows = []
        for data in data_list:
            warpl = str(data.get('WARPL') or '').strip().lstrip('0')
            nplda = str(data.get('NPLDA') or '').strip()
            equipment_no = str(data.get('EQUNR') or '').strip().lstrip('0')
            werks = str(data.get('WERKS') or data.get('IWERK') or '').strip()
            try:
                if len(nplda) != 8 or not nplda.isdigit():
                    raise ValueError
                planning_date = datetime.strptime(nplda, '%Y%m%d').date()
            except ValueError:
                _logger.warning("Invalid NPLDA %s skipped", nplda)
                continue
            if not equipment_no or not werks:
                _logger.warning(
                    "Preventif planning skipped: EQUNR or WERKS empty for NPLDA %s",
                    nplda,
                )
                continue
            parsed_rows.append((data, planning_date, equipment_no, werks))

        if not parsed_rows:
            return True

        companies = company_model.search([
            ('company_registry', 'in', list({row[3] for row in parsed_rows})),
            ('sync_pm', '=', True),
        ])
        companies_by_werks = {company.company_registry: company for company in companies}
        equipments = equip_model.search([
            ('equipment_no', 'in', list({row[2] for row in parsed_rows})),
            ('company_id', 'in', companies.ids),
        ])
        equipments_by_key = {
            (equipment.equipment_no, equipment.company_id.id): equipment
            for equipment in equipments
        }
        parent_equipments = equipments.filtered(lambda equipment: not equipment.parent_equipment_id)
        child_equipments = equip_model.search([('parent_equipment_id', 'in', parent_equipments.ids)], order='id')
        children_by_parent = {}
        for child_equipment in child_equipments:
            children_by_parent.setdefault(
                child_equipment.parent_equipment_id.id,
                child_equipment,
            )

        planning_rows = []
        for data, planning_date, equipment_no, werks in parsed_rows:
            company = companies_by_werks.get(werks)
            if not company:
                _logger.info("Company Plant %s preventif planning skipped", werks)
                continue
            equipment = equipments_by_key.get((equipment_no, company.id))
            if not equipment:
                _logger.info("Equipment %s preventif planning skipped", equipment_no)
                continue

            parent_equipment = equipment.parent_equipment_id
            equipment_id = parent_equipment.id or equipment.id
            sub_equipment_id = (
                equipment.id
                if parent_equipment
                else children_by_parent.get(equipment.id, equip_model).id
            )
            system_id = equipment.system_id.id
            sub_system_id = equipment.sub_system_id.id
            warpl = str(data.get('WARPL') or '').strip().lstrip('0')
            key = (
                company.id,
                warpl,
                planning_date,
                equipment_id,
                system_id,
                sub_system_id,
                sub_equipment_id,
            )
            planning_rows.append((data, company, key))

        if not planning_rows:
            return True

        planning_dates = {row[2][2] for row in planning_rows}
        date_from = self._parse_string_datetime(min(planning_dates).strftime('%Y%m%d'), '')
        date_to = self._parse_string_datetime((max(planning_dates) + timedelta(days=1)).strftime('%Y%m%d'), '')
        existing_work_orders = pm_wo_model.search([
            ('start_time', '>=', date_from),
            ('start_time', '<', date_to),
            ('company_id', 'in', list({row[2][0] for row in planning_rows})),
            ('maintenance_plan_number', 'in', list({row[2][1] for row in planning_rows})),
            ('equipment_id', 'in', list({row[2][3] for row in planning_rows})),
            ('is_maintenance_plan', '=', True),
        ])
        work_orders_by_key = defaultdict(lambda: pm_wo_model)
        for work_order in existing_work_orders:
            work_orders_by_key[
                (
                work_order.company_id.id,
                work_order.maintenance_plan_number or '',
                (work_order.start_time + timedelta(hours=7)).date(),
                work_order.equipment_id.id,
                work_order.system_id.id,
                work_order.sub_system_id.id,
                work_order.sub_equipment_id.id,
                )
            ] |= work_order

        sap_numbers = {
            str(data.get('AUFNR') or '').strip().lstrip('0')
            for data, _company, _key in planning_rows
            if str(data.get('AUFNR') or '').strip().lstrip('0')
        }
        work_orders_by_sap = defaultdict(lambda: pm_wo_model)
        if sap_numbers:
            sap_work_orders = pm_wo_model.search([
                ('company_id', 'in', list({row[2][0] for row in planning_rows})),
                ('wo_sap', 'in', list(sap_numbers)),
            ])
            for sap_work_order in sap_work_orders:
                work_orders_by_sap[
                    (sap_work_order.company_id.id, sap_work_order.wo_sap)
                ] |= sap_work_order

        delete_keys = {
            key
            for _data, _company, key in planning_rows
            if key[2] < delete_before
        }

        for data, company, key in planning_rows:
            (
                _company_id,
                warpl,
                planning_date,
                equipment_id,
                system_id,
                sub_system_id,
                sub_equipment_id,
            ) = key
            work_order = work_orders_by_key[key]
            nomor_wo = str(data.get('AUFNR') or '').strip().lstrip('0')
            description_planning = str(data.get('WPTXT') or '').strip()
            if key in delete_keys:
                if work_order:
                    work_order.unlink()
                    work_orders_by_key[key] = pm_wo_model
                continue
            if planning_date < today:
                continue
            if len(work_order) > 1:
                _logger.error(
                    "Duplicate preventive planning work orders for key %s: %s; skipped",
                    key,
                    work_order.ids,
                )
                continue
            sap_work_orders = work_orders_by_sap[(company.id, nomor_wo)] if nomor_wo else pm_wo_model
            if len(sap_work_orders) > 1:
                _logger.error(
                    "Duplicate preventive work orders for company %s and SAP WO %s: %s; skipped",
                    company.display_name,
                    nomor_wo,
                    sap_work_orders.ids,
                )
                continue
            if work_order:
                update_vals = {
                    'description_planning': description_planning,
                }
                if nomor_wo and not work_order.wo_sap:
                    if sap_work_orders and sap_work_orders != work_order:
                        _logger.error(
                            "Planning work order %s cannot use SAP WO %s already assigned to %s; skipped",
                            work_order.id,
                            nomor_wo,
                            sap_work_orders.ids,
                        )
                        continue
                    update_vals['wo_sap'] = nomor_wo
                    work_orders_by_sap[(company.id, nomor_wo)] = work_order
                    _logger.info(
                        "PLANNING PREVENTIF WORK ORDER %s linked to SAP WO %s",
                        work_order.id,
                        nomor_wo,
                    )
                elif nomor_wo and work_order.wo_sap != nomor_wo:
                    _logger.warning(
                        "PLANNING PREVENTIF WORK ORDER %s keeps SAP WO %s; incoming %s skipped",
                        work_order.id,
                        work_order.wo_sap,
                        nomor_wo,
                    )
                if self._needs_update(work_order, update_vals):
                    work_order.write(update_vals)
                continue

            start_time = self._parse_string_datetime(
                planning_date.strftime('%Y%m%d'),
                '',
            )
            vals = {
                'wo_sap': nomor_wo or False,
                'sap_synchronize': True,
                'system_id': system_id,
                'sub_system_id': sub_system_id,
                'equipment_id': equipment_id,
                'sub_equipment_id': sub_equipment_id,
                'company_id': company.id,
                'preventif_inspection': True,
                'start_time': start_time,
                'end_time': start_time,
                'maintenance_plan_number': warpl,
                'is_maintenance_plan': True,
                'description_planning': description_planning,
            }
            if sap_work_orders:
                work_order = sap_work_orders
                if self._needs_update(work_order, vals):
                    work_order.write(vals)
                _logger.info(
                    "SAP WORK ORDER %s linked to preventive planning %s",
                    nomor_wo,
                    warpl,
                )
            else:
                work_order = pm_wo_model.create(vals)
                if nomor_wo:
                    work_orders_by_sap[(company.id, nomor_wo)] = work_order
                work_order.message_post(body=f"PLANNING PREVENTIF WORK ORDER {nomor_wo or '-'} Created from Cron")
                _logger.info("PLANNING PREVENTIF WORK ORDER Created %s", nomor_wo)
            work_orders_by_key[key] = work_order

        return True


    @api.model
    def cron_reminder_wo_draft(self):
        work_orders = self.sudo()
        draft_wos = work_orders.search([
            ('wo_sap', '!=', False),
            ('state', '=', 'draft'),
            ('is_maintenance_plan', '=', False),
        ])
        if not draft_wos:
            _logger.info("Draft work order reminder skipped: no work orders found")
            return True

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        fallback_departments = self.env['tagging.department'].sudo().search([
            ('active', '=', True),
            ('company_id', 'in', draft_wos.company_id.ids),
            ('name', '=ilike', 'Maintenance%'),
        ])
        fallback_by_company = defaultdict(list)
        for department in fallback_departments:
            fallback_by_company[department.company_id.id].append(department)

        wos_by_dept = defaultdict(list)
        for wo in draft_wos:
            department = wo.tagging_id.department_id
            if not department:
                company_departments = fallback_by_company[wo.company_id.id]
                department = (
                    company_departments[0]
                    if len(company_departments) == 1 else False
                )
            if department and department.company_id == wo.company_id:
                wos_by_dept[department].append(wo)

        departments = self.env['tagging.department'].sudo().browse(
            [department.id for department in wos_by_dept]
        )
        pics = departments.mapped('pic_ids').filtered('active')
        pics |= self.env['tagging.pic'].sudo().search([
            ('active', '=', True),
            ('department_ids', 'in', departments.ids),
        ])
        now = fields.Datetime.now()

        mails = []
        for dept, wos in wos_by_dept.items():
            department_pics = pics.filtered(
                lambda pic: pic.department_id == dept
                or dept in pic.department_ids,
            )
            emails = sorted(set(tools.email_normalize_all(','.join(department_pics.mapped('email')))))
            if not emails:
                _logger.info("Draft work order reminder skipped: no recipient for department %s", dept.display_name)
                continue
            cc_emails = sorted(set(tools.email_normalize_all(','.join(filter(None, department_pics.mapped('cc'))))))

            rows = ""
            for i, wo in enumerate(wos, start=1):
                open_url = f"{base_url}/web#id={wo.id}&model=pm.work.order&view_type=form"
                wo_name = escape(wo.wo_sap or wo.name or '-')
                status = escape(dict(self._fields['state'].selection).get(wo.state, '-'))
                type_mo = escape(wo.type_mo or '-')
                system = escape(wo.system_id.name or '-')
                sub_system = escape(wo.sub_system_id.name or '-')
                created_on = (
                    fields.Datetime.context_timestamp(
                        wo.with_context(tz='Asia/Jakarta'),
                        wo.create_date,
                    ).strftime('%Y-%m-%d %H:%M:%S')
                    if wo.create_date else '-'
                )
                pending_days = max((now - wo.create_date).days, 0) if wo.create_date else 0
                
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
                        <td style="padding: 8px; text-align: right;">{pending_days} days</td>
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
                                <th style="padding: 8px;">Pending Duration</th>
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
                "auto_delete": False,
                "subject": subject,
                "body_html": body_html,
                "email_to": ",".join(emails),
                "email_from": "noreply-ops@cpp.co.id",
            }
            if cc_emails:
                mail_values['email_cc'] = ','.join(cc_emails)
            mails.append(mail_values)

        if mails:
            self.env['mail.mail'].sudo().create(mails)

        return True
