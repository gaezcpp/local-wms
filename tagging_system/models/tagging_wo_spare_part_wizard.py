from odoo import api, fields, models, _
from odoo.exceptions import UserError


class TaggingWOSparePartWizard(models.TransientModel):
    _name = "tagging.wo.sparepart.wizard"
    _description = "Wizard Input Sparepart sebelum Set WO"

    record_id = fields.Many2one("tagging.record", required=True, ondelete="cascade")

    equipment_id = fields.Many2one(
        "maintenance.equipment",
        string="Equipment",
        required=True,
    )

    # ✅ NEW: remarks sebelum confirm
    remarks = fields.Text(string="Remarks")

    line_ids = fields.One2many(
        "tagging.wo.sparepart.wizard.line", "wizard_id", string="Lines"
    )

    allowed_spare_part_ids = fields.Many2many(
        "product.product",
        compute="_compute_allowed_spare_part_ids",
        store=False,
        readonly=True,
    )

    @api.depends("equipment_id")
    def _compute_allowed_spare_part_ids(self):
        Product = self.env["product.product"].sudo()
        for wiz in self:
            eq = wiz.equipment_id
            if not eq:
                wiz.allowed_spare_part_ids = Product.browse([])
                continue

            tmp = self.env["tagging.wo.sparepart.wizard.line"].new({})
            plines = tmp._get_equipment_product_lines(eq)
            if not plines:
                wiz.allowed_spare_part_ids = Product.browse([])
                continue

            product_ids = tmp._extract_product_ids_from_plines(plines)
            wiz.allowed_spare_part_ids = Product.browse(product_ids or [])

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        rec_id = res.get("record_id")
        if rec_id:
            rec = self.env["tagging.record"].browse(rec_id)
            res["equipment_id"] = rec.equipment_id.id

        # bikin 1 baris line default supaya onchange/compute jalan dari awal
        if "line_ids" in fields_list or True:
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

        # bersihin line kosong
        (self.line_ids - valid_lines).unlink()

        # reset existing
        rec.write({"wo_sparepart_ids": [(5, 0, 0)]})

        vals_list = []
        for l in valid_lines:
            vals_list.append({
                "record_id": rec.id,
                "spare_part_id": l.spare_part_id.id,
                "specification": l.specification or "",
                "sku": l.sku or "",
                "qty": l.qty or 1.0,
                # ✅ NEW: simpan remarks dari header wizard ke tiap line persistent
                "remarks": self.remarks or "",
            })

        self.env["tagging.wo.sparepart"].sudo().create(vals_list)

        rec.write({"status": "open_wo"})
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
        store=False,
        readonly=True,
    )

    spare_part_id = fields.Many2one(
        "product.product",
        string="Spare Part",
        ondelete="restrict",
        index=True
    )

    specification = fields.Text(string="Spesifikasi Spare Part")
    sku = fields.Char(string="SKU", index=True)
    qty = fields.Float(string="Jumlah Spare Part", default=1.0)

    # -------------------------
    # Counter buttons (+ / -)
    # -------------------------
    def action_qty_minus(self):
        for line in self:
            line.qty = max(0.0, (line.qty or 0.0) - 1.0)

    def action_qty_plus(self):
        for line in self:
            line.qty = (line.qty or 0.0) + 1.0

    # -------------------------
    # Helpers
    # -------------------------
    def _get_equipment_product_lines(self, eq):
        if not eq:
            return None

        candidates = (
            "product_line_ids",
            "product_ids",
            "equipment_product_ids",
            "equipment_product_line_ids",
            "equipment_products_ids",
        )
        for name in candidates:
            if name in eq._fields:
                try:
                    return getattr(eq, name)
                except Exception:
                    continue

        for fname, field in eq._fields.items():
            if field.type != "one2many":
                continue
            if "product" not in fname:
                continue
            try:
                recs = getattr(eq, fname)
            except Exception:
                continue
            if recs is not None and (
                "product_id" in recs._fields or
                "product_tmpl_id" in recs._fields or
                "product_template_id" in recs._fields
            ):
                return recs

        return None

    def _extract_product_ids_from_plines(self, plines):
        Product = self.env["product.product"].sudo()

        if not plines:
            return []

        if getattr(plines, "_name", "") == "product.product":
            return plines.ids

        if "product_id" in plines._fields:
            return plines.mapped("product_id").ids

        tmpl_ids = []
        if "product_tmpl_id" in plines._fields:
            tmpl_ids = plines.mapped("product_tmpl_id").ids
        elif "product_template_id" in plines._fields:
            tmpl_ids = plines.mapped("product_template_id").ids

        if tmpl_ids:
            return Product.search([("product_tmpl_id", "in", tmpl_ids)]).ids

        return []

    # -------------------------
    # Onchange
    # -------------------------
    @api.onchange("spare_part_id")
    def _onchange_spare_part_id(self):
        for line in self:
            if line.spare_part_id:
                line.sku = line.spare_part_id.default_code or ""
                line.specification = (
                    line.spare_part_id.description_sale
                    or line.spare_part_id.description
                    or ""
                )
            else:
                line.specification = False
                line.sku = False
