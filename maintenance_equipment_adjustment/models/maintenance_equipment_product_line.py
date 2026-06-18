from odoo import fields, models, api, _

class MaintenanceEquipmentProductLine(models.Model):
    _name = "maintenance.equipment.product.line"
    _description = "Maintenance Equipment Product Line"
    _order = "id desc"

    equipment_id = fields.Many2one("maintenance.equipment", string="Equipment", ondelete="cascade")
    spare_part_id = fields.Many2one("tagging.spare_part", string="Spare Part", ondelete="restrict")
    sku = fields.Char(string="SKU")
    product_name = fields.Char(string="Name")
    qty = fields.Float(string="Qty")
    note = fields.Char(string="Note")