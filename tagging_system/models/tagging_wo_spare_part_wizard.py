from odoo import api, fields, models, _
from odoo.exceptions import UserError

class TaggingWOSparePartWizard(models.TransientModel):
    _name = "tagging.wo.sparepart.wizard"
    _description = "Wizard Input Sparepart sebelum Set WO"

    record_id = fields.Many2one("tagging.record", required=True, ondelete="cascade")
    line_ids = fields.One2many("tagging.wo.sparepart.wizard.line", "wizard_id", string="Lines")

    def action_confirm(self):
        self.ensure_one()
        rec = self.record_id.sudo()
        if not self.record_id:
            raise UserError(_("Record tidak ditemukan"))

        if rec.status != "validated":
            raise UserError(_("Set Work Order hanya bisa setelah Validated."))

        if not self.line_ids:
            raise UserError(_("Minimal input 1 spare part sebelum Set WO."))

        # hapus dulu kalau mau replace data sebelumnya
        rec.wo_sparepart_ids.unlink()

        vals_list = []
        for l in self.line_ids:
            vals_list.append({
                "record_id": rec.id,
                "machine_bom_id": l.machine_bom_id.id or False,
                "part_id": l.part_id.id or False,
                "spare_part_id": l.spare_part_id.id,
                "specification": l.specification or "",
                "sku": l.sku or "",
                "qty": l.qty or 1.0,
            })
        self.env["tagging.wo.sparepart"].sudo().create(vals_list)

        # setelah data tersimpan, baru ubah status
        rec.write({"status": "open_wo"})
        return {"type": "ir.actions.act_window_close"}


class TaggingWOSparePartWizardLine(models.TransientModel):
    _name = "tagging.wo.sparepart.wizard.line"
    _description = "Wizard Line Sparepart"

    wizard_id = fields.Many2one("tagging.wo.sparepart.wizard", required=True, ondelete="cascade")

    machine_bom_id = fields.Many2one("tagging.machine_bom", string="Kategori Unit Mesin", ondelete="restrict", index=True)
    part_id = fields.Many2one("tagging.machine_part", string="Kategori Bagian Mesin", ondelete="restrict", index=True)

    spare_part_id = fields.Many2one("tagging.spare_part", string="Spare Part", required=True, ondelete="restrict", index=True)
    specification = fields.Text(string="Spesifikasi Spare Part")
    sku = fields.Char(string="SKU", index=True)
    qty = fields.Float(string="Jumlah Spare Part", default=1.0)

    @api.onchange("machine_bom_id")
    def _onchange_machine_bom_id(self):
        for rec in self:
            # auto isi part + sparepart + spec + sku kalau BOM dipilih
            if rec.machine_bom_id:
                rec.part_id = rec.machine_bom_id.part_id
                rec.spare_part_id = rec.machine_bom_id.spare_part_id
                rec.specification = rec.machine_bom_id.specification or (rec.spare_part_id.specification or "")
                rec.sku = rec.machine_bom_id.sku or (rec.spare_part_id.sku or "")

    @api.onchange("spare_part_id")
    def _onchange_spare_part_id(self):
        for rec in self:
            if rec.spare_part_id:
                # kalau user pilih sparepart manual
                if not rec.specification:
                    rec.specification = rec.spare_part_id.specification or ""
                if not rec.sku:
                    rec.sku = rec.spare_part_id.sku or ""
