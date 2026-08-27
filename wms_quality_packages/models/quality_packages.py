from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from collections import defaultdict
from datetime import datetime, time
import pytz
import logging
_logger  = logging.getLogger(__name__)

class QualityPackages(models.Model):
    _name = 'quality.packages'
    _description = 'Quality Packages'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    
    name = fields.Char(string="Name", default="New")
    warehouse_id = fields.Many2one(comodel_name='stock.warehouse', string="Warehouse", tracking=True)
    product_id = fields.Many2one(comodel_name='product.product', string="Product", tracking=True)
    lot_id = fields.Many2one(comodel_name='stock.lot', string="Lot", tracking=True)
    location_id = fields.Many2one(comodel_name='stock.location', string="Location", tracking=True)
    action_aft_id = fields.Many2one(comodel_name='sap.aft', string="Action", tracking=True)
    company_id = fields.Many2one(comodel_name='res.company', string="Company", default=lambda self: self.env.company, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('cancel', 'Cancel'),
    ], string="State", default="draft", tracking=True)
    notes = fields.Text(string="Notes", tracking=True)
    quality_line_ids = fields.One2many('quality.packages.line', 'quality_packages_id')
    quality_summary_line_ids = fields.One2many('quality.packages.summary.line', 'quality_packages_id')
    is_checked = fields.Boolean(string="Is Checked", default=False, tracking=True)
    category_aft_id = fields.Many2one(comodel_name='category.quality.packages', string="Category", tracking=True)
    block_action_id = fields.Many2one(comodel_name='action.quality.packages', string="Block Action", tracking=True)
    other_reason = fields.Text(string="Other Reason", tracking=True)
    select_all = fields.Boolean(string="Select All", default=False)
    lot_stock_id = fields.Many2one(comodel_name='stock.location', string="Location Stock")
    production_shift_id = fields.Many2one(comodel_name='production.shift', string="Shift")
    production_line_id = fields.Many2one(comodel_name='production.line', string="Production Line")
    date_done = fields.Date(string="GR Date")
    done_time = fields.Datetime(string="End Date")
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('quality.packages') or 'New'
                
        return super().create(vals_list)
    
    @api.onchange('warehouse_id')
    def onchange_warehouse(self):
        if self.warehouse_id:
            self.lot_stock_id = self.warehouse_id.lot_stock_id.id
        else:
            self.lot_stock_id = False
    
    @api.onchange('warehouse_id', 'product_id', 'lot_id', 'location_id', 'action_aft_id')
    def _onchange_reset_checked(self):
        if self.is_checked:
            self.is_checked = False
            
    @api.onchange('select_all')
    def _onchange_select_all(self):
        self.ensure_one()
        for rec in self.quality_line_ids:
            if self.select_all:
                rec.is_selected = True
            else:
                rec.is_selected = False
    
    def _get_date_done_bounds(self):
        """Batas awal/akhir `date_done` dalam UTC.

        `date_done` adalah Date yang dipilih user dalam timezone-nya sendiri.
        Membandingkannya langsung dengan kolom Datetime (yang disimpan UTC)
        menggeser jendela sebesar offset timezone -- di WIB (+7) stok yang
        dibuat 00:00-07:00 hari itu hilang dan 00:00-07:00 hari berikutnya
        malah ikut terjaring.
        """
        self.ensure_one()
        tz = pytz.timezone(self.env.user.tz or 'UTC')
        date_from = tz.localize(datetime.combine(self.date_done, time.min))
        date_to = tz.localize(datetime.combine(self.date_done, time.max))
        return (
            date_from.astimezone(pytz.utc).replace(tzinfo=None),
            date_to.astimezone(pytz.utc).replace(tzinfo=None),
        )

    def _get_produced_stock_keys(self):
        """Kunci `(product_id, lot_id, package_id)` stok hasil produksi yang
        cocok dengan filter shift / tanggal pada record ini.

        Mengembalikan `None` kalau kedua filter kosong (tidak perlu disaring).

        Penyaringan dilakukan pada level penerimaan hasil produksi (picking
        `incoming`, state `done`) supaya yang terjaring benar-benar stok yang
        DIPRODUKSI pada shift/tanggal itu. Menyaring lewat `lot_id` saja salah:
        satu lot bisa diproduksi lintas beberapa shift/tanggal, sehingga seluruh
        stok lot tersebut ikut terbawa walau pallet-nya dari shift lain.

        Kalau move line penerimaannya tidak memasang package, kuncinya memakai
        `package_id = False` dan dicocokkan pada level `(product, lot)` saja.
        """
        self.ensure_one()
        if not self.production_shift_id and not self.date_done:
            return None

        domain = [
            ('state', '=', 'done'),
            ('lot_id', '!=', False),
            ('picking_id.picking_type_id.code', '=', 'incoming'),
        ]
        if self.company_id:
            domain.append(('company_id', '=', self.company_id.id))
        if self.production_shift_id:
            domain.append(('production_shift_id', '=', self.production_shift_id.id))
        if self.date_done:
            date_from, date_to = self._get_date_done_bounds()
            domain += [('date', '>=', date_from), ('date', '<=', date_to)]

        move_lines = self.env['stock.move.line'].sudo().search_fetch(
            domain, ['product_id', 'lot_id', 'result_package_id', 'package_id']
        )
        return {
            (
                ml.product_id.id,
                ml.lot_id.id,
                (ml.result_package_id or ml.package_id).id,
            )
            for ml in move_lines
        }

    def _prepare_quant_domain(self):
        """Domain `stock.quant` untuk Check Availability."""
        self.ensure_one()
        domain = [
            ('company_id', '=', self.company_id.id),
            ('location_id.usage', '=', 'internal'),
            # Quant sisa bernilai 0 tetap ada di DB; tanpa filter ini baris
            # kosong ikut muncul di detail dan terpilih oleh Select All.
            ('quantity', '>', 0),
            ('lot_id', '!=', False),
        ]
        if self.warehouse_id:
            domain.append(('warehouse_id', '=', self.warehouse_id.id))
        if self.product_id:
            domain.append(('product_id', '=', self.product_id.id))
        if self.lot_id:
            domain.append(('lot_id', '=', self.lot_id.id))
        if self.location_id:
            domain.append(('location_id', 'child_of', self.location_id.id))
        elif self.lot_stock_id and not self.warehouse_id:
            # `lot_stock_id` cuma turunan dari warehouse dan menunjuk lokasi
            # stok utama saja. Kalau warehouse sudah dipilih, filter warehouse
            # yang dipakai -- kalau tidak, pallet QI yang masih di staging
            # (mis. FINI/STG - IN) tidak akan pernah terlihat.
            domain.append(('location_id', 'child_of', self.lot_stock_id.id))
        if self.action_aft_id.stock_type_from:
            domain.append(('stock_type', '=', self.action_aft_id.stock_type_from))
        if self.production_line_id:
            # `stock.quant.production_line_id` diwarisi dari quant asal, jadi
            # bisa dipakai langsung -- tidak perlu memutar lewat stock.move.line.
            domain.append(('production_line_id', '=', self.production_line_id.id))
        return domain

    def _search_available_quants(self):
        self.ensure_one()
        quants = self.env['stock.quant'].sudo().search(self._prepare_quant_domain())
        keys = self._get_produced_stock_keys()
        if keys is None:
            return quants
        return quants.filtered(
            lambda q: (q.product_id.id, q.lot_id.id, q.package_id.id) in keys
            or (q.product_id.id, q.lot_id.id, False) in keys
        )

    def _prepare_quality_line_vals(self, quant):
        self.ensure_one()
        return {
            'quality_packages_id': self.id,
            'quant_id': quant.id,
            'product_id': quant.product_id.id,
            'package_id': quant.package_id.id or False,
            'location_id': quant.location_id.id,
            'lot_id': quant.lot_id.id,
            'quantity': quant.quantity,
            'uom_id': quant.product_uom_id.id,
            'bag_qty': quant.bag_qty,
            'uom_bag_id': quant.uom_bag_id.id or False,
            'po_sap_id': quant.po_sap_id.id or False,
            'pallet_ke': quant.pallet_ke or 0,
            'production_line_id': (
                quant.production_line_id.id or quant.lot_id.production_line_id.id or False
            ),
        }

    def check_availability(self):
        quality_line_model = self.env['quality.packages.line'].sudo()

        for rec in self:
            if rec.state != 'draft':
                continue

            # Dicari dulu sebelum apapun dihapus: kalau hasilnya kosong,
            # detail yang sudah ada tidak ikut hilang.
            quants = rec._search_available_quants()
            if not quants:
                raise ValidationError(
                    _("Packages tidak ditemukan untuk %s!", rec.name or _("record ini"))
                )

            rec.quality_line_ids.sudo().unlink()
            rec.quality_summary_line_ids.sudo().unlink()

            quality_line_model.create([
                rec._prepare_quality_line_vals(quant) for quant in quants
            ])

            rec.is_checked = True
            
    def action_in_progress(self):
        for rec in self:
            if rec.state == 'draft' and rec.is_checked:
                if len(rec.quality_line_ids) <= 0 or not rec.quality_line_ids:
                    raise ValidationError("Silahkan lakukan Check Availability terlebih untuk mengisi detail Packages")
                if not any(rec.quality_line_ids.mapped('is_selected')):
                    raise ValidationError("Minimal satu Packages harus dipilih sebelum melanjutkan ke In Progress!")
                
                not_selected = rec.quality_line_ids.filtered(lambda l: not l.is_selected)
                if not_selected:
                    not_selected.sudo().unlink()
                
                rec.state = 'in_progress'
            else:
                raise ValidationError("Hanya bisa ke In Progress jika Status Draft dan sudah Check Availability")
    
    def action_done(self):
        for rec in self:
            if rec.state != 'in_progress':
                raise ValidationError("Hanya bisa Done dari status In Progress!")

            selected_lines = rec.quality_line_ids.filtered(lambda l: l.is_selected and l.lot_id)
            if not selected_lines:
                raise ValidationError("Tidak ada Packages yang dipilih atau Packages yang dipilih Lotnya kosong!")

            stock_type_from = rec.action_aft_id.stock_type_from
            stock_type_to = rec.action_aft_id.stock_type_to
            is_to_block = stock_type_to and stock_type_to.strip().upper() == 'BLOCKED'
                
            if is_to_block and not rec.category_aft_id and not rec.block_action_id and not rec.other_reason:
                return self.action_open_aft_wizard()

            lot_totals = defaultdict(lambda: {'qty': 0.0, 'bag_qty': 0.0, 'uom_id': False, 'uom_bag_id': False, 'lot_obj': False})
            
            for line in selected_lines:
                if line.quantity <= 0:
                    _logger.warning(f"QualityPackages {rec.name}: Line lot {line.lot_id.name} memiliki quantity 0, dilewati.")
                    continue
                
                lot_id = line.lot_id.id
                lot_totals[lot_id]['qty'] += line.quantity
                lot_totals[lot_id]['bag_qty'] += line.bag_qty
                lot_totals[lot_id]['uom_id'] = line.uom_id.id
                lot_totals[lot_id]['uom_bag_id'] = line.uom_bag_id.id or False
                lot_totals[lot_id]['lot_obj'] = line.lot_id

            if not lot_totals:
                raise ValidationError("Tidak ada Packages dengan quantity lebih besar dari 0 yang dapat diproses!")

            lot_ids = list(lot_totals.keys())
            aft_records = self.env['stock.lot.aft'].sudo().search([
                ('lot_id', 'in', lot_ids),
                ('stock_type', 'in', [stock_type_from, stock_type_to])
            ])
            
            aft_map = {(r.lot_id.id, r.stock_type): r for r in aft_records}

            for lot_id, data in lot_totals.items():
                lot = data['lot_obj']
                qty_to_move = data['qty']
                bag_qty_to_move = data['bag_qty']

                aft_from = aft_map.get((lot_id, stock_type_from))
                if not aft_from:
                    aft_from = self.env['stock.lot.aft'].sudo().create({
                        'lot_id': lot_id,
                        'stock_type': stock_type_from,
                        'quantity': 0,
                        'bag_qty': 0,
                        'uom_id': data['uom_id'],
                        'uom_bag_id': data['uom_bag_id'],
                    })
                    aft_map[(lot_id, stock_type_from)] = aft_from

                aft_to = aft_map.get((lot_id, stock_type_to))
                if not aft_to:
                    aft_to = self.env['stock.lot.aft'].sudo().create({
                        'lot_id': lot_id,
                        'stock_type': stock_type_to,
                        'quantity': 0,
                        'bag_qty': 0,
                        'uom_id': data['uom_id'],
                        'uom_bag_id': data['uom_bag_id'],
                    })
                    aft_map[(lot_id, stock_type_to)] = aft_to

                new_aft_from_qty = max(0.0, aft_from.quantity - qty_to_move)
                new_aft_from_bag = max(0.0, aft_from.bag_qty - bag_qty_to_move)

                aft_from.write({
                    'quantity': new_aft_from_qty,
                    'bag_qty': new_aft_from_bag,
                })

                aft_to.write({
                    'quantity': aft_to.quantity + qty_to_move,
                    'bag_qty': aft_to.bag_qty + bag_qty_to_move,
                })

                lot.message_post(
                    body=(
                        f"Stock Lot AFT Updated from {rec.name}: "
                        f"{stock_type_from} -{bag_qty_to_move} (sisa: {new_aft_from_bag}) "
                        f"→ {stock_type_to} +{bag_qty_to_move} (total: {aft_to.bag_qty})"
                    )
                )

            valid_lines = selected_lines.filtered(lambda l: l.quantity > 0)
            
            quants_to_update = valid_lines.mapped('quant_id')
            if quants_to_update:
                quants_to_update.sudo().write({'stock_type': stock_type_to})
            
            packages_to_update = valid_lines.mapped('package_id')
            if packages_to_update:
                packages_to_update.sudo().write({'block_action_id': rec.block_action_id.id})

            rec.write({
                'state': 'done',
                'done_time': fields.Datetime.now()
            })
            rec._create_summary_line()
    
    def _create_summary_line(self):
        quality_summary_line = self.env['quality.packages.summary.line'].sudo()
        for rec in self:
            rec.quality_summary_line_ids.sudo().unlink()
            sap_aft = rec.action_aft_id
            if not sap_aft:
                continue

            lines_to_create = []
            for line in rec.quality_line_ids:
                lines_to_create.append({
                    'quality_packages_id': rec.id,
                    'product_id': line.lot_id.product_id.id if line.lot_id else False,
                    'package_id': line.package_id.id or False,
                    'location_id': line.location_id.id or False,
                    'lot_id': line.lot_id.id or False,
                    'quantity': line.quantity,
                    'uom_id': line.uom_id.id or False,
                    'bag_qty': line.bag_qty,
                    'uom_bag_id': line.uom_bag_id.id or False,
                    'stock_type_from': sap_aft.stock_type_from,
                    'stock_type_to': sap_aft.stock_type_to,
                    'move_type': sap_aft.move_type,
                    'po_sap_id': line.po_sap_id.id or False,
                    'pallet_ke': line.pallet_ke or 0,
                    'production_line_id': line.production_line_id.id or False,
                })

            if lines_to_create:
                quality_summary_line.create(lines_to_create)

    def action_set_draft(self):
        for rec in self:
            if rec.state == 'in_progress':
                rec.state = 'draft'
    
    def action_reject(self):
        for rec in self:
            if rec.state == 'done':
                raise ValidationError("Tidak bisa melakukan Cancel pada record yang sudah Done!")
            rec.quality_line_ids.sudo().unlink()
            rec.quality_summary_line_ids.sudo().unlink()
            rec.state = 'cancel'
            rec.message_post(body="Details dan Summary dihapus karena Cancel!")
    
    def action_open_aft_wizard(self):
        self.ensure_one()
        view = self.env.ref('wms_quality_packages.quality_packages_wizard_form_views')
        is_to_block = False
        if self.action_aft_id.stock_type_to.strip().upper() == 'BLOCKED':
            is_to_block = True
        return {
            'type': 'ir.actions.act_window',
            'name': 'Quality Packages AFT',
            'res_model': 'quality.packages.wizard',
            'views': [(view.id, 'form')],
            'target': 'new',
            'context': {
                'default_quality_packages_id': self.id,
                'default_is_to_block': is_to_block,
            }
        }