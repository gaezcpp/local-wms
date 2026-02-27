from odoo import models, fields, api
from odoo.exceptions import ValidationError
from odoo.tools.safe_eval import safe_eval

class StockInventoryAdjustment(models.Model):
    _name = 'stock.inventory.adjustment'
    _description = 'Stock Inventory Adjustment'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    
    name = fields.Char(string="Name")
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
        ('in_progress', 'In Progress'),
        ('validated', 'Validated'),
        ('cancelled', 'Cancelled')
    ], default='draft')
    notes = fields.Text(string="Notes")
    adjustment_line_ids = fields.One2many('stock.inventory.adjustment.line', 'stock_adjustment_id', copy=False)
    
    def _compute_quant_count(self):
        for rec in self:
            rec.quant_count = 1 if rec.quant_id else 0
    
    def action_in_progress(self):
        Quant = self.env['stock.quant'].sudo()
        for rec in self:
            if rec.state != 'draft':
                continue
            if not rec.product_id or not rec.location_id:
                raise ValidationError('Product and Location are required.')

            rec.adjustment_line_ids.unlink()

            domain = [
                ('product_id', '=', rec.product_id.id),
                ('location_id', '=', rec.location_id.id),
                ('company_id', '=', rec.company_id.id),
            ]
            if rec.lot_id:
                domain.append(('lot_id', '=', rec.lot_id.id))
            if rec.package_id:
                domain.append(('package_id', '=', rec.package_id.id))

            quant = Quant.search(domain, limit=1)

            system_qty = quant.quantity if quant else 0.0

            self.env['stock.inventory.adjustment.line'].create({
                'stock_adjustment_id': rec.id,
                'product_id': rec.product_id.id,
                'location_id': rec.location_id.id,
                'lot_id': rec.lot_id.id if rec.lot_id else False,
                'package_id': rec.package_id.id if rec.package_id else False,
                'system_qty': system_qty,
                'counted_qty': rec.counted_qty,
            })

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

                quant.inventory_quantity = line.counted_qty
                quant.action_apply_inventory()

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
                ('product_id', '=', rec.product_id.id),
                ('location_id', '=', rec.location_id.id),
                ('company_id', '=', rec.company_id.id),
            ]
            rec.quant_count = Quant.search_count(domain)
    
    def action_view_quant(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Physical Inventory',
            'view_mode': 'list',
            'res_model': 'stock.quant',
            'domain': [
                ('product_id', '=', self.product_id.id),
                ('location_id', '=', self.location_id.id),
            ],
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
        }
        
        print(f"action_open_barcode_inventory.action {action}")

        return action