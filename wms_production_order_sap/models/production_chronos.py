from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ProductionChronos(models.Model):
    _name = 'production.chronos'
    _description = 'Production Chronos'
    _rec_name = 'name'
    _order = 'id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    name = fields.Char(string="Name", default="New")
    po_sap_id = fields.Many2one(comodel_name='production.order.sap', string="PO SAP", tracking=True, index=True)
    production_shift_id = fields.Many2one(comodel_name='production.shift', string="Shift", tracking=True, index=True)
    production_line_id = fields.Many2one(comodel_name='production.line', string="Line", tracking=True, index=True)
    counter_awal = fields.Float(string="Counter Awal", tracking=True)
    counter_akhir = fields.Float(string="Counter Akhir", tracking=True)
    counter_total = fields.Float(string="Total Counter", compute='_compute_counter_total')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
        ('cancel', 'Cancel'),
    ], string="State", default='draft', tracking=True)
    company_id = fields.Many2one(comodel_name='res.company', string="Company", default=lambda self: self.env.company, tracking=True)
    is_checked = fields.Boolean(string="Is Checked", default=False)
    po_chronos_line_ids = fields.One2many('production.chronos.line', 'po_chronos_id')
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('production.chronos') or _('New')
        res = super().create(vals_list)
        return res
    
    @api.depends('counter_awal', 'counter_akhir')
    def _compute_counter_total(self):
        for rec in self:
            rec.counter_total = ((rec.counter_akhir - rec.counter_awal) + 1)
    
    @api.onchange('po_sap_id', 'production_shift_id', 'production_line_id', 'company_id')
    def _onchange_is_check(self):
        for rec in self:
            if rec.is_checked:
                rec.is_checked = False
    
    def get_detail_production_chronos(self):
        picking_model = self.env['stock.picking'].sudo()
        po_chronos_line_model = self.env['production.chronos.line'].sudo()

        lines_to_create = []
        for rec in self:
            if rec.state != 'draft':
                continue
            
            rec.po_chronos_line_ids.sudo().unlink()
            
            domain = [
                ('company_id', '=', rec.company_id.id),
                ('po_sap_id', '=', rec.po_sap_id.id),
                ('production_shift_id', '=', rec.production_shift_id.id),
                ('picking_type_id.move_type_sap', '=', '888'),
                ('state', '=', 'done'),
            ]
            pickings = picking_model.search(domain)
            
            if not pickings:
                rec.is_checked = False
                raise ValidationError("Picking List tidak ditemukan!")
            
            for pick in pickings:
                valid_moves = pick.move_ids.filtered(
                    lambda m: any(sml.production_line_id.id == rec.production_line_id.id for sml in m.move_line_ids)
                )
                for move in valid_moves:
                    lines_to_create.append({
                        'po_chronos_id': rec.id,
                        'picking_id': pick.id,
                        'warehouse_id': pick.picking_type_id.warehouse_id.id,
                        'product_id': move.product_id.id,
                        'quantity': move.quantity,
                        'product_uom_id': move.product_uom.id,
                        'pack_qty': move.bag_qty, 
                        'product_pack_id': move.uom_bag_id.id,
                    })
            
            rec.is_checked = True
            
        if lines_to_create:
            po_chronos_line_model.create(lines_to_create)
            
    def action_done(self):
        for rec in self:
            if rec.state != 'draft':
                raise ValidationError("Hanya bisa melakukan Done saat Status Draft")
            if not rec.po_sap_id or not rec.production_shift_id:
                raise ValidationError("PO SAP atau Shift tidak boleh kosong!")
            if not rec.production_line_id:
                raise ValidationError("Production Line tidak boleh kosong!")
            if not rec.is_checked or len(rec.po_chronos_line_ids) <= 0:
                raise ValidationError("Silahkan lakukan Get Details terlebih dahulu")
            if rec.counter_awal <= 0:
                raise ValidationError("Counter Awal tidak boleh kurang dari 0!")
            if rec.counter_akhir <= 0:
                raise ValidationError("Counter Akhir tidak boleh kurang dari 0!")
            if rec.counter_awal > rec.counter_akhir:
                raise ValidationError("Counter Awal tidak boleh melebihi Counter Akhir")
            
            rec.state = 'done'
    
    def action_cancel(self):
        for rec in self:
            if rec.state == 'draft':
                rec.state = 'cancel'
            else:
                raise ValidationError("Hanya bisa melakukan Cancel saat Status Draft")
            