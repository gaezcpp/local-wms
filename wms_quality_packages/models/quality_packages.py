from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
_logger  = logging.getLogger(__name__)

class QualityPackages(models.Model):
    _name = 'quality.packages'
    _description = 'Quality Packages'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    
    name = fields.Char(string="Name", default="New")
    product_id = fields.Many2one(comodel_name='product.product', string="Product", tracking=True)
    lot_id = fields.Many2one(comodel_name='stock.lot', string="Lot", tracking=True)
    location_id = fields.Many2one(comodel_name='stock.location', string="Location", tracking=True)
    action_aft_id = fields.Many2one(comodel_name='sap.aft', string="Action", tracking=True)
    company_id = fields.Many2one(comodel_name='res.company', string="Company", default=lambda self: self.env.company, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('reject', 'Reject'),
    ], string="State", default="draft", tracking=True)
    notes = fields.Text(string="Notes", tracking=True)
    quality_line_ids = fields.One2many('quality.packages.line', 'quality_packages_id')
    quality_summary_line_ids = fields.One2many('quality.packages.summary.line', 'quality_packages_id')
    is_checked = fields.Boolean(string="Is Checked", default=False, tracking=True)
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('quality.packages') or _('New')
        return super().create(vals_list)
    
    def check_availability(self):
        quant_model = self.env['stock.quant'].sudo()
        quality_line_model = self.env['quality.packages.line'].sudo()

        for rec in self:
            if rec.state != 'draft':
                continue

            rec.quality_line_ids.sudo().unlink()
            rec.quality_summary_line_ids.sudo().unlink()

            domain = [
                ('company_id', '=', rec.company_id.id),
                ('location_id.usage', '=', 'internal'),
            ]
            if rec.product_id:
                domain.append(('product_id', '=', rec.product_id.id))
            if rec.lot_id:
                domain.append(('lot_id', '=', rec.lot_id.id))
            if rec.location_id:
                domain.append(('location_id', 'child_of', rec.location_id.id))

            if rec.action_aft_id and rec.action_aft_id.stock_type_from:
                domain.append(('stock_type', '=', rec.action_aft_id.stock_type_from))

            quants = quant_model.search(domain)
            if not quants:
                raise ValidationError("Packages tidak ditemukan!")

            for quant in quants:
                if not quant.lot_id:
                    continue

                quality_line_model.create({
                    'quality_packages_id': rec.id,
                    'package_id': quant.package_id.id or False,
                    'location_id': quant.location_id.id,
                    'lot_id': quant.lot_id.id,
                    'quantity': quant.quantity,
                    'uom_id': quant.product_uom_id.id,
                    'bag_qty': quant.bag_qty,
                    'uom_bag_id': quant.uom_bag_id.id or False,
                })

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
            if not rec.action_aft_id:
                raise ValidationError("Action belum dipilih!")

            selected_lines = rec.quality_line_ids.filtered(lambda l: l.is_selected and l.lot_id)
            if not selected_lines:
                raise ValidationError("Tidak ada Packages yang dipilih atau Packages yang dipilih Lotnya kosong!")

            stock_type_from = rec.action_aft_id.stock_type_from
            stock_type_to = rec.action_aft_id.stock_type_to

            for line in selected_lines:
                lot = line.lot_id
                aft_from = lot.lot_aft_ids.filtered(lambda la: la.stock_type == stock_type_from)
                aft_to = lot.lot_aft_ids.filtered(lambda la: la.stock_type == stock_type_to)

                if not aft_from:
                    aft_from = self.env['stock.lot.aft'].sudo().create({
                        'lot_id': lot.id,
                        'stock_type': stock_type_from,
                        'quantity': 0,
                        'bag_qty': 0,
                        'uom_id': line.uom_id.id or False,
                        'uom_bag_id': line.uom_bag_id.id or False,
                    })

                if not aft_to:
                    aft_to = self.env['stock.lot.aft'].sudo().create({
                        'lot_id': lot.id,
                        'stock_type': stock_type_to,
                        'quantity': 0,
                        'bag_qty': 0,
                        'uom_id': line.uom_id.id or False,
                        'uom_bag_id': line.uom_bag_id.id or False,
                    })

                total_quantity = aft_from.quantity
                total_bag_qty = aft_from.bag_qty

                aft_from.write({
                    'quantity': 0,
                    'bag_qty': 0,
                })

                aft_to.write({
                    'quantity': aft_to.quantity + total_quantity,
                    'bag_qty': aft_to.bag_qty + total_bag_qty,
                })

                quant_domain = [
                    ('lot_id', '=', lot.id),
                    ('stock_type', '=', stock_type_from),
                ]
                if line.package_id:
                    quant_domain.append(('package_id', '=', line.package_id.id))
                if line.location_id:
                    quant_domain.append(('location_id', '=', line.location_id.id))

                matching_quants = self.env['stock.quant'].sudo().search(quant_domain)
                if matching_quants:
                    matching_quants.write({'stock_type': stock_type_to})

                lot.message_post(
                    body=f"Stock Lot AFT Updated from {rec.name}: "
                        f"{stock_type_from} -{total_quantity} → {stock_type_to} +{total_quantity}"
                )

            rec.state = 'done'
        self._create_summary_line()
    
    def _create_summary_line(self):
        quality_summary_line = self.env['quality.packages.summary.line'].sudo()
        for rec in self:
            rec.quality_summary_line_ids.sudo().unlink()
            
            sap_aft = rec.action_aft_id
            if not sap_aft:
                continue

            for line in rec.quality_line_ids:
                quality_summary_line.create({
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
                })

    def action_set_draft(self):
        for rec in self:
            if rec.state == 'in_progress':
                rec.state = 'draft'
            
    def action_reject(self):
        for rec in self:
            rec.quality_line_ids.sudo().unlink()
            rec.quality_summary_line_ids.sudo().unlink()
            rec.message_post(body="Details dan Summary dihapus!")
            rec.state = 'reject'