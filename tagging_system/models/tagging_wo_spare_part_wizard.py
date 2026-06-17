from odoo import api, fields, models, _
from odoo.exceptions import UserError


class TaggingWOSparePartWizard(models.TransientModel):
    _name = "tagging.wo.sparepart.wizard"
    _description = "Wizard Input Sparepart sebelum Set WO"

    record_id = fields.Many2one("tagging.record", required=True, ondelete="cascade")
    equipment_id = fields.Many2one("maintenance.equipment", string="Equipment", required=True,)
    line_ids = fields.One2many("tagging.wo.sparepart.wizard.line", "wizard_id", string="Lines")
    allowed_spare_part_ids = fields.Many2many("tagging.spare_part", compute="_compute_allowed_spare_part_ids")

    @api.depends("equipment_id")
    def _compute_allowed_spare_part_ids(self):
        SparePart = self.env["tagging.spare_part"].sudo()
        for wiz in self:
            plines = wiz.equipment_id.product_line_ids if wiz.equipment_id else None
            if not plines:
                wiz.allowed_spare_part_ids = SparePart
                continue

            sku_list = list(filter(None, plines.mapped("sku")))
            company_id = wiz.equipment_id.company_id.id

            wiz.allowed_spare_part_ids = (
                SparePart.search([("sku", "in", sku_list), ("company_id", "=", company_id)])
                if sku_list else SparePart
            )

    # @api.depends("equipment_id")
    # def _compute_allowed_spare_part_ids(self):
    #     SparePart = self.env["tagging.spare_part"].sudo()
    #     print(f"XXXXXXXX {SparePart}")

    #     for wiz in self:
    #         if not wiz.equipment_id:
    #             wiz.allowed_spare_part_ids = SparePart.browse()
    #             continue

    #         plines = wiz._get_equipment_product_lines()

    #         if not plines:
    #             wiz.allowed_spare_part_ids = SparePart.browse()
    #             continue

    #         product_ids = wiz._extract_spare_part_ids(plines)
    #         wiz.allowed_spare_part_ids = SparePart.browse(product_ids)

    # def _get_equipment_product_lines(self):
    #     self.ensure_one()
    #     eq = self.equipment_id

    #     if not eq:
    #         return self.env["maintenance.equipment.product.line"]

    #     # langsung target field yang jelas
    #     if "product_line_ids" in eq._fields:
    #         return eq.product_line_ids

    #     return self.env["maintenance.equipment.product.line"]

    # def _extract_spare_part_ids(self, plines):
    #     SparePart = self.env["tagging.spare_part"].sudo()

    #     if not plines:
    #         return []

    #     # CASE 1: sku adalah Char
    #     if "sku" in plines._fields and plines._fields["sku"].type == "char":
    #         sku_list = list(filter(None, plines.mapped("sku")))
    #         return SparePart.search([("sku", "in", sku_list)]).ids

    #     # CASE 2: sku adalah Many2one ke spare part
    #     if "sku" in plines._fields and plines._fields["sku"].type == "many2one":
    #         return plines.mapped("sku").ids

    #     return []

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        rec_id = res.get("record_id")
        if rec_id:
            rec = self.env["tagging.record"].browse(rec_id)
            res["equipment_id"] = rec.equipment_id.id

        if "line_ids" not in res or not res["line_ids"]:
            res["line_ids"] = [(0, 0, {})]

        return res

    def action_confirm(self):
        self.ensure_one()

        rec = self.record_id.sudo()

        if rec.status != "validated":
            raise UserError(_("Set Work Order hanya bisa setelah Validated."))

        valid_lines = self.line_ids.filtered(lambda l: l.spare_part_id)

        if not valid_lines:
            raise UserError(_("Minimal input 1 spare part sebelum Set WO."))
        
        seen_spare_parts = set()
        for line in valid_lines:
            if line.spare_part_id.id in seen_spare_parts:
                raise UserError(
                    f"Spare Part '{line.spare_part_id.display_name}' tidak boleh diinput lebih dari satu kali. "
                    "Silakan gabungkan jumlah (qty) menjadi satu baris atau hapus baris yang ganda.")
            seen_spare_parts.add(line.spare_part_id.id)

        (self.line_ids - valid_lines).unlink()

        rec.write({"wo_sparepart_ids": [(5, 0, 0)]})

        vals_list = []
        
        msg_body = "WO Spare Part Updated:\n"
        for l in valid_lines:
            vals_list.append({
                "record_id": rec.id,
                "spare_part_id": l.spare_part_id.id,
                "specification": l.specification or "",
                "sku": l.spare_part_id.sku or '',
                "qty": l.qty or 1.0,
                "remarks": l.remarks or "",
            })
            sku_info = f" [{l.spare_part_id.sku}]" if l.spare_part_id.sku else ""
            remarks_info = f" - Catatan: {l.remarks}" if l.remarks else ""
            msg_body += f"- {l.spare_part_id.display_name}{sku_info} | Qty: {l.qty}{remarks_info}\n"

        self.env["tagging.wo.sparepart"].sudo().create(vals_list)
        rec.message_post(body=msg_body)

        return {"type": "ir.actions.act_window_close"}
    
class TaggingWOSparePartWizardLine(models.TransientModel):
    _name = "tagging.wo.sparepart.wizard.line"
    _description = "Wizard Line Sparepart"

    wizard_id = fields.Many2one(
        "tagging.wo.sparepart.wizard",
        required=True,
        ondelete="cascade"
    )

    equipment_id = fields.Many2one(
        "maintenance.equipment",
        related="wizard_id.equipment_id",
    )

    spare_part_id = fields.Many2one(
        "tagging.spare_part",
        string="Spare Part",
        ondelete="restrict",
    )

    specification = fields.Text(string="Spesifikasi Spare Part")
    sku = fields.Char(string="SKU")
    qty = fields.Float(string="Jumlah Spare Part", default=1.0)
    remarks = fields.Char(string="Reason")

    def action_qty_minus(self):
        for line in self:
            line.qty = max(0.0, (line.qty or 0.0) - 1.0)

    def action_qty_plus(self):
        for line in self:
            line.qty = (line.qty or 0.0) + 1.0

    @api.onchange("spare_part_id")
    def _onchange_spare_part_id(self):
        for line in self:
            if line.spare_part_id:
                line.sku = line.spare_part_id.sku or ""
                line.specification or ""
            else:
                line.sku = False
                line.specification = False