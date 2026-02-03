# -*- coding: utf-8 -*-

from odoo import fields, models, api, _
from odoo.exceptions import UserError, ValidationError


class StockInventoryLine(models.Model):
    _name = 'stock.inventory.line'
    _description = 'Inventory line'

    stock_inventory_id = fields.Many2one('stock.inventory',index=True)
    product_id = fields.Many2one(
        'product.product', 'Product',
        index=True, required=True)
    product_uom_id = fields.Many2one(
        'uom.uom', 'Product Unit of Measure',
        required=True,
        readonly=True,
        related='product_id.uom_id',
        )
    location_id = fields.Many2one(
        'stock.location', 'Location',
        index=True, required=True, related='stock_inventory_id.location_id')
    prod_lot_id = fields.Many2one(
        'stock.lot', 'Lot Number',
        domain="[('product_id','=',product_id), ]", )
    package_id = fields.Many2one(
        'stock.package', 'Pack', index=True)
    partner_id = fields.Many2one('res.partner', 'Owner')
    available_quantity = fields.Float(
        'Available Quantity',
        help="On hand quantity which hasn't been reserved on a transfer, in the default unit of measure of the product",
        digits='Product Unit of Measure', readonly=True)
    quantity = fields.Float(
        'Quantity On Hand',
        help='Quantity of products in this quant, in the default unit of measure of the product',
        readonly=True, 
        digits='Product Unit of Measure')
    inventory_quantity = fields.Float(
        'Counted Quantity', digits='Product Unit of Measure',
        help="The product's counted quantity.")
    make_it_zero = fields.Boolean('Set Zero')
    state = fields.Selection(
        string='Status',  related='stock_inventory_id.state', readonly=True)
    company_id = fields.Many2one(
        'res.company', 'Company', related='stock_inventory_id.company_id',
        index=True, readonly=True, store=True)

    lot_serial = fields.Boolean(string='Serial', compute="compute_lot_serial_require")
    lot_id = fields.Boolean(string='Lot', compute="compute_lot_serial_require")
    currency_id = fields.Many2one('res.currency', 'Currency', related='company_id.currency_id', readonly=True, required=True)
    price_value = fields.Monetary('Diff. Valuation', compute="compute_total_price")
    reserved_quantity = fields.Float('Reserved Quantity',readonly=True, digits='Product Reserved Quantity', compute="_compute_reserved_quantity", store=True)

    @api.depends('product_id', 'product_uom_id')
    def _compute_reserved_quantity(self):
        for line in self:
            line.reserved_quantity = line.quantity - line.available_quantity

    def compute_total_price(self):
        for record in self:
            record.price_value = (record.inventory_quantity - record.quantity) * record.product_id.standard_price

    @api.depends('product_id')
    def compute_lot_serial_require(self):
        for line in self:
            line.lot_serial = False
            if line.product_id.tracking == 'serial':
                line.lot_serial = True
            line.lot_id = False
            if line.product_id.tracking == 'lot':
                line.lot_id = True

    def do_unreserve_product_qty(self):
        move = self.env['stock.move.line'].search([('product_id', '=', self.product_id.id), ('location_id', '=', self.stock_inventory_id.location_id.id),('state', 'not in', ('done', 'cancel'))])
        move.mapped('move_id').filtered(lambda x: x.state not in ('done', 'cancel'))._do_unreserve()
        self.reserved_quantity = 0
        self.available_quantity = self.quantity

    @api.onchange('product_id', 'prod_lot_id')
    def onchange_product_id(self):
        for line in self:
            domain = [('company_id', '=', line.stock_inventory_id.company_id.id),
                    ('location_id', '=', line.stock_inventory_id.location_id.id),
                    ]
            if line.stock_inventory_id and line.stock_inventory_id.partner_id:
                donain.append(('owner_id', '=', line.stock_inventory_id.partner_id.id),)
            if line.product_id.tracking == 'none':
                quant_rec = self.env['stock.quant'].search(domain + [('product_id','=',line.product_id.id)])
                if quant_rec:
                    line.available_quantity = quant_rec.available_quantity
                    line.quantity = quant_rec.quantity 
                    line.inventory_quantity = quant_rec.inventory_quantity
            if line.product_id.tracking != 'none' and line.prod_lot_id:                
                line.available_quantity = line.prod_lot_id.product_qty
                line.quantity = line.prod_lot_id.product_qty 

    def select_stock_inventory_line(self):
        same_product_records = self.env['stock.inventory.line'].search([('product_id','=',self.product_id.id),('stock_inventory_id','=',self.stock_inventory_id.id)])
        selection_record = self.env['inventory.selection'].create({'product_id': self.product_id.id, 'stock_inventory_id':self.stock_inventory_id.id})
        selection_line_id = []
        for line in same_product_records.filtered(lambda x: x.quantity):
            selection_line_id.append((0,0,{
                'inventory_selection_id':selection_record.id,
                'prod_lot_id':line.prod_lot_id.id,
                'quantity_on_hand':line.quantity,
                'stock_inventory_line_id':line.id,
                'quantity':0,
            }))
        if selection_line_id:
            selection_record.write({'selection_line_id':selection_line_id})

        return {
            'name': "Add Products",
            'view_mode': 'form',
            'view_type': 'form',
            'view_id': self.env.ref("inventory_stock_adjustments.inventory_selection_form_view").id,
            'res_model': 'inventory.selection',
            'res_id':selection_record.id,
            'type': 'ir.actions.act_window',
            'target': 'new',
        }

    @api.onchange('make_it_zero', 'inventory_quantity')
    def onchange_make_zero(self):
        for rec in self:
            if rec.make_it_zero:
                rec.inventory_quantity = 0.0