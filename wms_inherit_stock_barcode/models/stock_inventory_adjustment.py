from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools.safe_eval import safe_eval

class StockInventoryAdjustment(models.Model):
    _name = 'stock.inventory.adjustment'
    _description = 'Stock Inventory Adjustment'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    
    name = fields.Char(string="Name", default="New")
    user_id = fields.Many2one(comodel_name='res.users', string="User", default=lambda self:self.env.user)
    product_id = fields.Many2one(comodel_name='product.product', string="Product")
    location_id = fields.Many2one(comodel_name='stock.location', index=True)
    company_id = fields.Many2one(comodel_name='res.company', default=lambda self:self.env.company, string="Company")
    date_time = fields.Datetime(string="Inventory Date", default=fields.Datetime.now())
    lot_id = fields.Many2one(comodel_name='stock.lot', string="Lot Number")
    package_id = fields.Many2one(comodel_name='stock.package', string="Package")
    quant_id = fields.Many2one(comodel_name='stock.quant', string="Quant")
    counted_qty = fields.Float(string="Counted Quantity")
    quant_count = fields.Integer(compute='_compute_quant_count')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('ready', 'Ready'),
        ('in_progress', 'In Progress'),
        ('validated', 'Validated'),
        ('cancelled', 'Cancelled')
    ], default='draft')
    notes = fields.Text(string="Notes")
    stock_type = fields.Selection([
        ('QI', 'QI'),
        ('Blocked', 'Blocked'),
        ('UU', 'UU')], string="Stock Type", default=False)
    is_checked = fields.Boolean(string="Is Checked?", default=False)
    adjustment_line_ids = fields.One2many('stock.inventory.adjustment.line', 'stock_adjustment_id', copy=False, ondelete='cascade')
    summary_line_ids = fields.One2many('stock.inventory.adjustment.summary', 'stock_adjustment_id', copy=False, ondelete='cascade')
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('stock.inventory.adjustment') or _('New')
        res = super().create(vals_list)
        return res
    
    def check_details(self):
        Quant = self.env['stock.quant'].sudo()
        for rec in self:
            if rec.state != 'draft':
                continue

            rec.adjustment_line_ids.unlink()

            domain = [
                ('company_id', '=', rec.company_id.id),
            ]
            
            if rec.product_id:
                domain.append(('product_id', '=', rec.product_id.id))
            if rec.location_id:
                domain.append(('location_id', '=', rec.location_id.id))
            if rec.package_id:
                domain.append(('package_id', '=', rec.package_id.id))
            if rec.stock_type:
                domain.append(('package_id.state', '=', rec.stock_type))
            if rec.lot_id:
                domain.append(('lot_id', '=', rec.lot_id.id))

            quant = Quant.search(domain)
            if not quant:
                raise ValidationError("Physical Inventory not found!")
            
            for q in quant:
                self.env['stock.inventory.adjustment.line'].create({
                    'stock_adjustment_id': rec.id,
                    'product_id': q.product_id.id,
                    'location_id': q.location_id.id,
                    'lot_id': q.lot_id.id if q.lot_id else False,
                    'package_id': q.package_id.id if q.package_id else False,
                    'package_status': q.package_id.state if q.package_id else False,
                    'quantity': q.quantity,
                    'inventory_quantity': q.inventory_quantity,
                    'inventory_diff_quantity': q.inventory_diff_quantity,
                })
            
            rec.is_checked = True
            self.action_detail_operation()
            
    def action_detail_operation(self):
        for rec in self:
            if not rec.is_checked:
                continue

            rec.summary_line_ids.unlink()
            grouped_data = {}

            for line in rec.adjustment_line_ids:
                key = (
                    line.product_id.id,
                    "FINI",
                    line.package_id.state if line.package_id else False
                )

                if key not in grouped_data:
                    grouped_data[key] = {
                        'quantity': 0.0,
                        'inventory_quantity': 0.0,
                        'inventory_diff_quantity': 0.0,
                    }

                grouped_data[key]['quantity'] += line.quantity
                grouped_data[key]['inventory_quantity'] += line.inventory_quantity
                grouped_data[key]['inventory_diff_quantity'] += line.inventory_diff_quantity

            for (product_id, sloc_name, stock_type), vals in grouped_data.items():
                self.env['stock.inventory.adjustment.summary'].sudo().create({
                    'stock_adjustment_id': rec.id,
                    'product_id': product_id,
                    'sloc_name': sloc_name,
                    'stock_type': stock_type,
                    'quantity': vals['quantity'],
                    'inventory_quantity': vals['inventory_quantity'],
                    'inventory_diff_quantity': vals['inventory_diff_quantity'],
                })
    
    def action_in_progress(self):
        for rec in self:
            if rec.state == 'draft':
                if not rec.is_checked:
                    raise ValidationError("Details dan Operations belum terisi, silahkan lakukan Get Details terlebih dahulu!")
                
                rec.state = 'in_progress'

    def action_validated(self):
        Quant = self.env['stock.quant'].sudo()
        for rec in self:
            if rec.state != 'in_progress':
                continue

            for line in rec.adjustment_line_ids:
                domain = [
                    ('product_id', '=', line.product_id.id),
                    ('location_id', '=', line.location_id.id),
                    ('company_id', '=', rec.company_id.id),
                ]
                if line.lot_id:
                    domain.append(('lot_id', '=', line.lot_id.id))
                if line.package_id:
                    domain.append(('package_id', '=', line.package_id.id))

                quant = Quant.search(domain, limit=1)
                if not quant:
                    quant = Quant.create({
                        'product_id': line.product_id.id,
                        'location_id': line.location_id.id,
                        'company_id': rec.company_id.id,
                        'lot_id': line.lot_id.id if line.lot_id else False,
                        'package_id': line.package_id.id if line.package_id else False,
                    })

                # quant.action_apply_inventory()

            rec.state = 'validated'

    def action_cancelled(self):
        for rec in self:
            if rec.state in ('draft', 'in_progress'):
                rec.state = 'cancelled'

    def _compute_quant_count(self):
        Quant = self.env['stock.quant'].sudo()
        for rec in self:
            if not rec.adjustment_line_ids:
                rec.quant_count = 0
                continue
            domain = [
                ('company_id', '=', rec.company_id.id),
            ]
            
            if rec.product_id:
                domain.append(('product_id', '=', rec.product_id.id))
            if rec.location_id:
                domain.append(('location_id', '=', rec.location_id.id))
            if rec.package_id:
                domain.append(('package_id', '=', rec.package_id.id))
            if rec.stock_type:
                domain.append(('package_id.state', '=', rec.stock_type))
            if rec.lot_id:
                domain.append(('lot_id', '=', rec.lot_id.id))
            
            rec.quant_count = Quant.search_count(domain)
    
    def action_view_quant(self):
        self.ensure_one()
        domain = [
            ('company_id', '=', self.company_id.id),
        ]
        
        if self.product_id:
            domain.append(('product_id', '=', self.product_id.id))
        if self.location_id:
            domain.append(('location_id', '=', self.location_id.id))
        if self.package_id:
            domain.append(('package_id', '=', self.package_id.id))
        if self.stock_type:
            domain.append(('package_id.state', '=', self.stock_type))
        if self.lot_id:
            domain.append(('lot_id', '=', self.lot_id.id))
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Physical Inventory',
            'view_mode': 'list',
            'res_model': 'stock.quant',
            'domain': domain,
        }
    
    def action_open_barcode_inventory(self):
        self.ensure_one()

        action = self.env['ir.actions.actions']._for_xml_id(
            'stock_barcode.stock_barcode_inventory_client_action'
        )

        action['context'] = {
            'active_id': False,
            'active_ids': [],
            'active_model': False,
            'default_location_barcode': self.location_id.barcode or '',
            'auto_submit_barcode': True,
        }
        
        print(f"action_open_barcode_inventory.action {action}")

        return action

    def action_open_kanban_barcode(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Stock Opname',
            'view_mode': 'kanban',
            'res_model': 'stock.inventory.adjustment',
            'domain': [
                ('id', '=', self.id),
            ],
        }