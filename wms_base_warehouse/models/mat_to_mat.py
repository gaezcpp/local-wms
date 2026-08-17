from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class MatToMat(models.Model):
    _name = 'mat.to.mat'
    _description = 'Material to Material'
    _rec_name = 'name'
    _order = 'id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    name = fields.Char(string="Name", default="New")
    date_done = fields.Date(string="Date Done")
    company_id = fields.Many2one(comodel_name='res.company', string="Company", default=lambda self:self.env.company)
    move_type = fields.Char(string="Move Type")
    select_all = fields.Boolean(string="Select All")
    is_checked = fields.Boolean(string="Is Checked")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting', 'Waiting'),
        ('ready', 'Ready'),
        ('done', 'Done'),
        ('cancel', 'Cancel'),
    ], string="State", default='draft', tracking=True)
    warehouse_id = fields.Many2one(comodel_name='stock.warehouse', string="Warehouse")
    product_id = fields.Many2one(comodel_name='product.product', string="Source Product")
    product_dest_id = fields.Many2one(comodel_name='product.product', string="Destination Product")
    location_id = fields.Many2one(comodel_name='stock.location', string="Source Location")
    notes = fields.Text(string="Notes")
    mat_source_ids = fields.One2many('mat.to.mat.source', 'mat_to_mat_id')
    mat_destination_ids = fields.One2many('mat.to.mat.destination', 'mat_to_mat_id')
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('mat.to.mat') or 'New'
                
        return super().create(vals_list)
    
    @api.onchange('warehouse_id', 'product_id', 'lot_id', 'location_id')
    def _onchange_reset_checked(self):
        if self.is_checked:
            self.is_checked = False
    
    @api.onchange('select_all')
    def _onchange_select_all(self):
        for rec in self.mat_source_ids:
            if self.select_all:
                rec.is_selected = True
            else:
                rec.is_selected = False
                
    def action_check_availibility(self):
        pass
                
    def action_mat_ready(self):
        pass
        
    def action_mat_done(self):
        pass
        
    def action_mat_cancel(self):
        pass
    
class MatToMatSource(models.Model):
    _name = 'mat.to.mat.source'
    _description = 'Mat to Mat Source'
    
    mat_to_mat_id = fields.Many2one(comodel_name='mat.to.mat')
    quant_id = fields.Many2one(comodel_name='stock.quant')
    location_id = fields.Many2one(comodel_name='stock.location', string="Location")
    product_id = fields.Many2one(comodel_name='product.product', string="Product")
    package_id = fields.Many2one(comodel_name='stock.package', string="Package")
    lot_id = fields.Many2one(comodel_name='stock.lot', string="Lot")
    quantity = fields.Float(string="Quantity")
    uom_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    pack_qty = fields.Float(string="Pack Qty")
    pack_uom_id = fields.Many2one(comodel_name='uom.uom', string="Units")
    stock_type = fields.Selection([
        ('QI', 'QI'),
        ('BLOCKED', 'BLOCKED'),
        ('UU', 'UU'),
    ], string="Stock Type")
    is_selected = fields.Boolean(string="Select")
    
    
class MatToMatDestination(models.Model):
    _name = 'mat.to.mat.destination'
    _description = 'Mat to Mat Destination'
    
    mat_to_mat_id = fields.Many2one(comodel_name='mat.to.mat')
    quant_id = fields.Many2one(comodel_name='stock.quant')
    location_id = fields.Many2one(comodel_name='stock.location', string="Location")
    product_id = fields.Many2one(comodel_name='product.product', string="Product")
    package_id = fields.Many2one(comodel_name='stock.package', string="Package")
    lot_id = fields.Many2one(comodel_name='stock.lot', string="Lot")
    quantity = fields.Float(string="Quantity")
    uom_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    pack_qty = fields.Float(string="Pack Qty")
    pack_uom_id = fields.Many2one(comodel_name='uom.uom', string="Units")
    stock_type = fields.Selection([
        ('QI', 'QI'),
        ('BLOCKED', 'BLOCKED'),
        ('UU', 'UU'),
    ], string="Stock Type")