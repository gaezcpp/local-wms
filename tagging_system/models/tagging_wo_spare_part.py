from odoo import api, fields, models, _
from odoo.exceptions import UserError

class TaggingWOSparePart(models.Model):
    _name = "tagging.wo.sparepart"
    _description = "Tagging WO Sparepart (Persistent)"
    _order = "id desc"

    record_id = fields.Many2one("tagging.record", required=True, ondelete="cascade", index=True)
    machine_bom_id = fields.Many2one("tagging.machine_bom", string="Kategori Unit Mesin", ondelete="restrict", index=True)

    # kategori bagian mesin (ambil dari bom)
    part_id = fields.Many2one("tagging.machine_part", string="Kategori Bagian Mesin", ondelete="restrict", index=True)

    spare_part_id = fields.Many2one("tagging.spare_part", string="Spare Part", required=True, ondelete="restrict", index=True)
    specification = fields.Text(string="Spesifikasi Spare Part")
    sku = fields.Char(string="SKU", index=True)

    qty = fields.Float(string="Jumlah Spare Part", default=1.0)

    @api.onchange("spare_part_id")
    def _onchange_spare_part_id(self):
        for rec in self:
            if rec.spare_part_id:
                rec.specification = rec.spare_part_id.specification or ""
                rec.sku = rec.spare_part_id.sku or ""
