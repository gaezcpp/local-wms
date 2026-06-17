from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class DailyCycleCount(models.Model):
    _name = 'daily.cycle.count'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Daily Cycle Count'
    _order = 'id desc'
    
    user_id = fields.Many2one(comodel_name='res.users', string="User", default=lambda self: self.env.user.id)
    company_id = fields.Many2one(comodel_name='res.company', string="Company", default=lambda self: self.env.company)
    location_id = fields.Many2one(comodel_name='stock.location', string="Location")
    product_id = fields.Many2one(comodel_name='product.product', string="Product")
    lot_id = fields.Many2one(comodel_name='stock.lot', string="Production Code")
    package_id = fields.Many2one(comodel_name='stock.package', string="Package")
    inventory_date = fields.Date(string="Scheduled", default=fields.Date.context_today)
    quantity = fields.Float(string="Quantity")
    inventory_quantity = fields.Float(string="Counted")
    inventory_diff_quantity = fields.Float(string="Difference", compute='_compute_inventory_diff_quantity', store=True)
    inventory_quantity_set = fields.Boolean(string="Quantity Set", default=False)
    product_uom_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    stock_type = fields.Selection([
        ('QI', 'QI'),
        ('BLOCKED', 'BLOCKED'),
        ('UU', 'UU'),
    ], string="Stock Type")
    pack_qty = fields.Float(string="Pack Qty")
    pack_unit_id = fields.Many2one(comodel_name='uom.uom', string="Unit Pack")
    pallet_qty = fields.Float(string="Pallet Qty")
    uom_pallet_id = fields.Many2one(comodel_name='uom.uom', string="Unit Pallet")
    dummy_id = fields.Char(compute='_compute_dummy_id', inverse='_inverse_dummy_id')
    product_reference_code = fields.Char(related="product_id.code", string="Product Reference Code")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
    ], string="State", default='draft')

    @api.depends('quantity', 'inventory_quantity')
    def _compute_inventory_diff_quantity(self):
        for record in self:
            record.inventory_diff_quantity = record.inventory_quantity - record.quantity

    def _compute_dummy_id(self):
        for record in self:
            record.dummy_id = ''

    def _inverse_dummy_id(self):
        pass
    
    @api.onchange('quantity', 'uom_pallet_id')
    def _onchange_pallet_qty(self):
        for line in self:
            if line.quantity and line.uom_pallet_id:
                line.pallet_qty = line.quantity / (line.uom_pallet_id.factor / 1000)
            else:
                line.pallet_qty = 0.0
    
    @api.onchange('pack_qty')
    def _onchange_pack_qty(self):
        for line in self:
            if not line.pack_qty:
                line.quantity = 0.0
                continue
            
            if line.pack_unit_id and line.pack_unit_id.factor:
                line.quantity = line.pack_qty * (line.pack_unit_id.factor / 1000)
    
    @api.model
    def barcode_write(self, vals):
        """ Specially made to handle barcode app saving directly to daily.cycle.count. """
        RecordModel = self.env['daily.cycle.count']

        # Handle lot creation if scanning a new lot
        for val in vals:
            if val[0] in (0, 1) and not val[2].get('lot_id') and val[2].get('lot_name'):
                record_db = val[0] == 1 and RecordModel.browse(val[1]) or False
                
                # Fetch related location to get the correct company
                loc_id = val[2].get('location_id') or (record_db and record_db.location_id.id)
                company_id = self.env['stock.location'].browse(loc_id).company_id.id if loc_id else self.env.company.id
                
                val[2]['lot_id'] = self.env['stock.lot'].create({
                    'name': val[2].pop('lot_name'),
                    'product_id': val[2].get('product_id', record_db and record_db.product_id.id or False),
                    'company_id': company_id
                }).id

        record_ids = []
        for val in vals:
            if val[0] == 1:
                record_id = val[1]
                RecordModel.browse(record_id).write(val[2])
                record_ids.append(record_id)
            elif val[0] == 0:
                record = RecordModel.create(val[2])
                if val[2].get('dummy_id'):
                    record.write({'dummy_id': val[2].get('dummy_id')})
                if val[2].get('inventory_date'):
                    record.write({'inventory_date': val[2].get('inventory_date')})
                    
                user_id = val[2].get('user_id')
                if not record.user_id and user_id:
                    record.write({'user_id': user_id})
                record_ids.append(record.id)
                
        return self.browse(record_ids)._get_stock_barcode_data()
    
    def action_validate(self):
        # Filter hanya record yang belum selesai
        records = self.filtered(lambda q: q.inventory_quantity_set and q.state != 'done')
        
        if records:
            # Kalkulasi selisih
            records._compute_inventory_diff_quantity()
            # Ubah status
            records.write({'state': 'done'})
            
        return {'type': 'ir.actions.client', 'tag': 'reload'}
    
    def action_client_action(self):
        action = self.env['ir.actions.actions']._for_xml_id('wms_inherit_stock_barcode.stock_barcode_daily_cycle_count_client_action')
        return action
    
    def _get_stock_barcode_data(self):
        locations = self.env['stock.location']
        company_id = self.env.company.id
        package_types = self.env['stock.package.type']
        valid_records = self
        
        if not self:  # `self` is an empty recordset when we open the inventory adjustment.
            warehouse_location = self.env['stock.warehouse'].search([('company_id', '=', company_id)], limit=1).lot_stock_id
            quant_locations = self.env['stock.location']
            if self.env.user.has_group('stock.group_stock_multi_locations'):
                quant_locations = self.env['stock.location'].search([
                    ('usage', 'in', ['internal', 'transit']),
                    ('company_id', '=', company_id),
                ], order='id')
            else:
                quant_locations = warehouse_location
                
            valid_records = self.env['daily.cycle.count'].search([
                ('state', '!=', 'done'),
                '|',
                    ('user_id', '=?', self.env.user.id),
                    ('user_id', '=', False),
                ('location_id', 'in', quant_locations.ids),
                ('inventory_date', '<=', fields.Date.today()),
            ])
            locations = warehouse_location.child_internal_location_ids | valid_records.location_id
            if self.env.user.has_group('stock.group_tracking_lot'):
                package_types = package_types.search([])

        data = valid_records.with_context(display_default_code=False, barcode_view=True).get_stock_barcode_data_records()
        if locations:
            data["records"]["stock.location"] = locations.read(locations._get_fields_stock_barcode(), load=False)
        if package_types:
            data["records"]["stock.package.type"] = package_types.read(package_types._get_fields_stock_barcode(), load=False)
        data['line_view_id'] = self.env.ref('wms_inherit_stock_barcode.daily_cycle_count_barcode').id
        return data
    
    def get_stock_barcode_data_records(self):
        products = self.product_id
        companies = self.company_id or self.env.company
        lots = self.lot_id
        packages = self.package_id
        uoms = products.uom_id | products.uom_ids
        if self.env.user.has_group('uom.group_uom'):
            uoms = self.env['uom.uom'].search([])

        data = {
            "records": {
                "daily.cycle.count": self.read(self._get_fields_stock_barcode(), load=False),
                "product.product": products.read(products._get_fields_stock_barcode(), load=False),
                "stock.package": packages.read(packages._get_fields_stock_barcode(), load=False),
                "res.company": companies.read(['name']),
                "stock.lot": lots.read(lots._get_fields_stock_barcode(), load=False),
                "uom.uom": uoms.read(uoms._get_fields_stock_barcode(), load=False),
            },
            "nomenclature_id": [self.env.company.nomenclature_id.id],
            "user_id": self.env.user.id,
        }
        return data
    
    def _get_fields_stock_barcode(self):
        return [
            'user_id',
            'location_id',
            'product_id',
            'lot_id',
            'package_id',
            'inventory_date',
            'quantity',
            'inventory_quantity',
            'inventory_diff_quantity',
            'inventory_quantity_set',
            'product_uom_id',
            'stock_type',
            'pack_qty',
            'pack_unit_id',
            'pallet_qty',
            'uom_pallet_id',
            'dummy_id',
            'state',
            'company_id',
        ]
        
    def _get_inventory_fields_write(self):
        return [
            'inventory_date', 'inventory_quantity', 'inventory_quantity_set', 
            'user_id', 'location_id', 'lot_id', 'package_id', 'dummy_id'
        ]
    
    def _get_stock_barcode_specific_data(self):
        return {
            'product.product': self.product_id.read(self.env['product.product']._get_fields_stock_barcode(), load=False),
            'uom.uom': self.product_id.uom_id.read(self.env['uom.uom']._get_fields_stock_barcode(), load=False),
            'stock.location': self.location_id.read(self.env['stock.location']._get_fields_stock_barcode(), load=False),
            'stock.lot': self.lot_id.read(self.env['stock.lot']._get_fields_stock_barcode(), load=False),
            'stock.package': self.package_id.read(self.env['stock.package']._get_fields_stock_barcode(), load=False),
        }