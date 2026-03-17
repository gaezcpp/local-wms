from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class TaggingDepartment(models.Model):
    _name = "tagging.department"
    _description = "Tagging Department"
    _order = "name asc"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        ondelete="restrict",
    )


class TaggingBU(models.Model):
    _name = "tagging.bu"
    _description = "Business Unit"
    _order = "name asc"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("tagging_bu_code_uniq", "unique(code)", "Business Unit code must be unique."),
    ]
    
class TaggingPic(models.Model):
    _name = "tagging.pic"
    _description = "Tagging PIC"
    _order = "email asc"
    _rec_name = "email"

    email = fields.Char(string="Email PIC", required=True)
    cc = fields.Text(string="CC Emails")  # <--- TEXT, bukan Boolean

    department_ids = fields.Many2many(
        "tagging.department",
        "tagging_pic_department_rel",
        "pic_id",
        "department_id",
        string="Department",
    )

    bu_ids = fields.Many2many(
        "tagging.bu",
        "tagging_pic_bu_rel",
        "pic_id",
        "bu_id",
        string="BU",
    )

    active = fields.Boolean(default=True)
