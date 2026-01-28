from odoo import models, fields

class CategoryProblem(models.Model):
    _name = 'category.problem'
    _description = 'Category Problem Master'
    _rec_name = 'cat_masalah'

    sistem = fields.Char(string='Sistem', required=True)
    sub_sistem = fields.Char(string='Sub Sistem', required=True)
    cat_masalah = fields.Char(string='Category Masalah', required=True)
    active = fields.Boolean(default=True)
