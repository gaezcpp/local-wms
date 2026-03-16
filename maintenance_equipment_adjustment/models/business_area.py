# -*- coding: utf-8 -*-
from odoo import fields, models

class MaintenanceBusinessArea(models.Model):
    _name = "maintenance.business.area"
    _description = "Maintenance Business Area"
    _order = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
