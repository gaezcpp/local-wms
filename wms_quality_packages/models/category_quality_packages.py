from odoo import models, fields, api
from odoo.exceptions import ValidationError


class CategoryQualityPackages(models.Model):
    _name = 'category.quality.packages'
    _description = 'Category Quality Packages'
    _rec_name = 'name'
    
    name = fields.Char(string="Name")