from odoo import models, fields


class TaggingSystem(models.Model):
    _name = "tagging.system"
    _description = "Tagging System"
    _order = "name asc"

    name = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)


class TaggingSubSystem(models.Model):
    _name = "tagging.subsystem"
    _description = "Tagging Sub System"
    _order = "name asc"

    name = fields.Char(required=True, index=True)
    system_id = fields.Many2one("tagging.system", required=True, ondelete="cascade", index=True)
    active = fields.Boolean(default=True)


class TaggingMachineUnit(models.Model):
    _name = "tagging.machine_unit"
    _description = "Tagging Unit Mesin"
    _order = "name asc"

    name = fields.Char(required=True, index=True)
    subsystem_id = fields.Many2one("tagging.subsystem", required=True, ondelete="cascade", index=True)
    bu_id = fields.Many2one("tagging.bu", required=True, ondelete="restrict", index=True)
    active = fields.Boolean(default=True)


class TaggingMachinePart(models.Model):
    _name = "tagging.machine_part"
    _description = "Tagging Bagian Mesin"
    _order = "name asc"

    name = fields.Char(required=True, index=True)
    unit_id = fields.Many2one("tagging.machine_unit", required=True, ondelete="cascade", index=True)
    active = fields.Boolean(default=True)


class TaggingSparePart(models.Model):
    _name = "tagging.spare_part"
    _description = "Tagging Spare Part Master"
    _order = "name asc"

    name = fields.Char(required=True, index=True)
    specification = fields.Text(string="Spesifikasi Spare Part")
    sku = fields.Char(string="SKU", index=True)
    bu_id = fields.Many2one("tagging.bu", string="BU", ondelete="restrict", index=True)
    active = fields.Boolean(default=True)


class TaggingMachineBOM(models.Model):
    """
    1 record = 1 baris Excel:
    sistem | sub_sistem | unit_mesin | bagian_mesin | spare_part | spesifikasi | sku | bu
    """
    _name = "tagging.machine_bom"
    _description = "Equipment Tree / BOM"
    _order = "system_id, subsystem_id, unit_id, part_id, spare_part_id"

    system_id = fields.Many2one("tagging.system", required=True, ondelete="restrict", index=True)
    subsystem_id = fields.Many2one(
        "tagging.subsystem",
        required=True,
        ondelete="restrict",
        index=True,
        domain="[('system_id', '=', system_id)]",
    )
    unit_id = fields.Many2one(
        "tagging.machine_unit",
        required=True,
        ondelete="restrict",
        index=True,
        domain="[('subsystem_id', '=', subsystem_id)]",
    )
    part_id = fields.Many2one(
        "tagging.machine_part",
        required=True,
        ondelete="restrict",
        index=True,
        domain="[('unit_id', '=', unit_id)]",
    )

    spare_part_id = fields.Many2one("tagging.spare_part", required=True, ondelete="restrict", index=True)

    # snapshot dari excel (biar gampang cari tanpa buka sparepart master)
    specification = fields.Text(string="Spesifikasi (Snapshot)")
    sku = fields.Char(string="SKU (Snapshot)", index=True)
    bu_id = fields.Many2one("tagging.bu", string="BU (Snapshot)", ondelete="restrict", index=True)

    active = fields.Boolean(default=True)
