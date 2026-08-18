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
            if not vals.get('move_type', ''):
                vals['move_type'] = self.env['ir.config_parameter'].sudo().get_param('mattomat_move_type_sap')
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
        quant_model = self.env['stock.quant'].sudo()
        source_mtm_model = self.env['mat.to.mat.source'].sudo()
        dest_mtm_model = self.env['mat.to.mat.destination'].sudo()
        
        for rec in self:
            if rec.state != 'draft':
                continue
            
            rec.mat_source_ids.sudo().unlink()
            rec.mat_destination_ids.sudo().unlink()
        
            source_domain = [
                ('company_id', '=', rec.company_id.id),
                ('location_id.usage', '=', 'internal'),
            ]
            dest_domain = [
                ('company_id', '=', rec.company_id.id),
                ('location_id.usage', '=', 'internal'),
            ]
            
            if rec.warehouse_id:
                source_domain.append(('warehouse_id', '=', rec.warehouse_id.id))
                dest_domain.append(('warehouse_id', '=', rec.warehouse_id.id))
            if rec.product_id:
                source_domain.append(('product_id', '=', rec.product_id.id))
            if rec.product_dest_id:
                dest_domain.append(('product_id', '=', rec.product_dest_id.id))
            if rec.location_id:
                source_domain.append(('location_id', 'child_of', rec.location_id.id))
                dest_domain.append(('location_id', 'child_of', rec.location_id.id))
            
            source_quant = quant_model.search(source_domain)
            dest_quant = quant_model.search(dest_domain)
            if not source_quant and not dest_quant:
                raise ValidationError("Data tidak ditemukan!")
            
            source_to_create = []
            dest_to_create = []
            
            for quant in source_quant:
                source_to_create.append({
                    'mat_to_mat_id': rec.id,
                    'quant_id': quant.id,
                    'product_id': quant.product_id.id or False,
                    'package_id': quant.package_id.id or False,
                    'location_id': quant.location_id.id,
                    'lot_id': quant.lot_id.id,
                    'quantity': quant.quantity,
                    'uom_id': quant.product_uom_id.id,
                    'pack_qty': quant.bag_qty,
                    'pack_uom_id': quant.uom_bag_id.id or False,
                })
            for quant in dest_quant:
                dest_to_create.append({
                    'mat_to_mat_id': rec.id,
                    'quant_id': quant.id,
                    'product_id': quant.product_id.id or False,
                    'package_id': quant.package_id.id or False,
                    'location_id': quant.location_id.id,
                    'lot_id': quant.lot_id.id,
                    'quantity': quant.quantity,
                    'uom_id': quant.product_uom_id.id,
                    'pack_qty': quant.bag_qty,
                    'pack_uom_id': quant.uom_bag_id.id or False,
                })
            
            if source_to_create:
                source_mtm_model.create(source_to_create)
            if dest_to_create:
                dest_mtm_model.create(dest_to_create)
        
            rec.is_checked = True
                
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