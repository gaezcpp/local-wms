from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import datetime, timedelta
import pytz
import logging
import random
_logger = logging.getLogger(__name__)


class ZmoReport(models.Model):
    _name = 'zmo.report'
    _description = 'ZMO Report'
    _rec_name = 'nomor_mo'
    _order = 'id desc'
    
    nomor_mo = fields.Char(string="Nomor MO")
    order_type = fields.Char(string="Order Type")
    plan = fields.Char(string="Plan")
    start_date = fields.Char(string="Start Date")
    end_date = fields.Char(string="End Date")
    equipment_code = fields.Char(string="Equipment Code")
    equipment_desc = fields.Char(string="Equipment Desc")
    func_loc_code = fields.Char(string="Func Loc Code")
    func_loc_desc = fields.Char(string="Func Loc Desc")
    material_sku = fields.Char(string="Material SKU")
    material_desc = fields.Char(string="Material Desc")
    quantity = fields.Char(string="Quantity")
    plan_cost = fields.Char(string="Plan Cost")
    act_cost = fields.Char(string="Actual Cost")
    
    def generate_dummy_data(self):
        count = self.env.context.get('dummy_count', 10)
        
        order_types = ['PM01', 'PM02', 'PM03', 'PM04']
        plans = ['Maintenance', 'Inspection', 'Repair', 'Overhaul']
        equipments = ['Genset', 'Pompa', 'Kompresor', 'Turbin']
        areas = ['Produksi', 'Gudang', 'Utility', 'Packaging']
        
        for _ in range(count):
            start = datetime.now() - timedelta(days=random.randint(1, 30))
            end = start + timedelta(days=random.randint(1, 5))
            
            vals = {
                'nomor_mo': f"MO-{random.randint(10000, 99999)}",
                'order_type': random.choice(order_types),
                'plan': random.choice(plans),
                'start_date': start.strftime('%Y-%m-%d'),
                'end_date': end.strftime('%Y-%m-%d'),
                'equipment_code': f"EQ-{random.randint(100, 999)}",
                'equipment_desc': f"Mesin {random.choice(equipments)}",
                'func_loc_code': f"FL-{random.randint(10, 99)}",
                'func_loc_desc': f"Area {random.choice(areas)}",
                'material_sku': f"SKU-{random.randint(1000, 9999)}",
                'material_desc': f"Sparepart Tipe {random.choice(['A', 'B', 'C', 'D'])}",
                'quantity': str(random.randint(1, 50)),
                'plan_cost': str(random.randint(1000000, 5000000)),
                'act_cost': str(random.randint(900000, 5500000)),
            }
            self.create(vals)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }