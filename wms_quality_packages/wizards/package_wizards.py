from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from collections import defaultdict

class PackageWizards(models.TransientModel):
    _name = 'package.wizards'
    _description = 'Package Wizards'

    quality_package_id = fields.Many2one(comodel_name='quality.packages', string="Quality Packages", required=True)
    package_wizards_ids = fields.One2many('package.wizards.line', 'package_wizard_id', string="Package Wizards Line")
    partial_update = fields.Boolean(string="Partial Update?", default=False)
    state = fields.Selection([
        ('QI', 'QI'),
        ('Blocked', 'Blocked'),
        ('UU', 'UU'),
    ], default=False, string="State")

    @api.onchange('partial_update')
    def _onchange_partial_update(self):
        self.state = False
        if len(self.package_wizards_ids) > 0:
            for line in self.package_wizards_ids:
                line.state_after = False

    def action_update_state(self):
        self.ensure_one()

        if not self.package_wizards_ids:
            raise UserError("Package harus lebih dari 0")

        grouped = defaultdict(list)
        auto_revert_packages = []
        updated_packages = []

        if self.partial_update:
            for line in self.package_wizards_ids:
                if not line.state_after:
                    raise UserError("State After wajib diisi")
                if line.package_id:
                    package = line.package_id
                    old_state = package.state
                    new_state = line.state_after

                    if new_state in ('UU', 'Blocked') and not package.contained_quant_ids:
                        auto_revert_packages.append((package.name, old_state))
                        final_state = 'QI'
                    else:
                        final_state = new_state

                    grouped[new_state].append(package.id)
                    updated_packages.append((package.name, old_state, final_state))
        else:
            if not self.state:
                raise UserError("State wajib diisi")
            for line in self.package_wizards_ids:
                if line.package_id:
                    package = line.package_id
                    old_state = package.state
                    new_state = self.state

                    if new_state in ('UU', 'Blocked') and not package.contained_quant_ids:
                        auto_revert_packages.append((package.name, old_state))
                        final_state = 'QI'
                    else:
                        final_state = new_state

                    grouped[new_state].append(package.id)
                    updated_packages.append((package.name, old_state, final_state))

        package_obj = self.env['stock.package'].sudo()
        for state, ids in grouped.items():
            package_obj.browse(ids).write({'state': state})

        self.quality_package_id.write({'state': 'completed'})

        message_lines = []
        for name, old_state, final_state in updated_packages:
            message_lines.append(f"- {name} {old_state} -> {final_state}")

        if auto_revert_packages:
            message_lines.append("")
            message_lines.append("Package tanpa isi otomatis dikembalikan ke QI")

        self.quality_package_id.message_post(body="\n".join(message_lines))

class PackageWizardsLine(models.TransientModel):
    _name = 'package.wizards.line'
    _description = 'Package Wizards Line'

    package_wizard_id = fields.Many2one(comodel_name='package.wizards')
    package_id = fields.Many2one(comodel_name='stock.package', string="Package")
    parent_package_id = fields.Many2one(comodel_name='stock.package', string="Container")
    package_type_id = fields.Many2one(comodel_name='stock.package.type', string="Package Type")
    location_id = fields.Many2one(comodel_name='stock.location', string="Location")
    pallet_status = fields.Selection([
        ('full_pallet', 'Full Pallet'),
        ('eceran', 'Eceran')
    ], default=False, string="Pallet Status")
    pack_date = fields.Datetime(string="Pack Date")
    state = fields.Selection([
        ('QI', 'QI'),
        ('Blocked', 'Blocked'),
        ('UU', 'UU'),
    ], default=False, string="State")
    state_after = fields.Selection([
        ('QI', 'QI'),
        ('Blocked', 'Blocked'),
        ('UU', 'UU'),
    ], default=False, string="State Update")