from odoo import api, fields, models, _
from odoo.exceptions import UserError


class TaggingWOSparePart(models.Model):
    _name = "tagging.wo.sparepart"
    _description = "Tagging WO Sparepart (Persistent)"
    _order = "id desc"

    record_id = fields.Many2one(
        "tagging.record",
        required=True,
        ondelete="cascade",
        index=True,
    )

    machine_bom_id = fields.Many2one(
        "tagging.machine_bom",
        string="Kategori Unit Mesin",
        ondelete="restrict",
        index=True,
    )

    equipment_id = fields.Many2one(
        "maintenance.equipment",
        string="Equipment",
        related="record_id.equipment_id",
        store=False,
        readonly=True,
    )

    part_id = fields.Many2one(
        "tagging.machine_part",
        string="Kategori Bagian Mesin",
        ondelete="restrict",
        index=True,
    )

    spare_part_id = fields.Many2one(
        "product.product",
        string="Spare Part",
        required=True,
        ondelete="restrict",
        index=True,
    )

    specification = fields.Text(string="Spesifikasi Spare Part")
    sku = fields.Char(string="SKU", index=True)
    qty = fields.Float(string="Jumlah Spare Part", default=1.0)

    remarks = fields.Text(string="Remarks", required=True)

    # ---------------------------------------------------------
    # Helper: ambil product.product dari BOM spare_part_id (kalau BOM masih tagging.spare_part)
    # ---------------------------------------------------------
    def _bom_to_product(self, bom_sparepart):
        if not bom_sparepart:
            return self.env["product.product"].browse()

        if getattr(bom_sparepart, "_name", "") == "product.product":
            return bom_sparepart

        if getattr(bom_sparepart, "_name", "") == "tagging.spare_part":
            if "product_id" in bom_sparepart._fields and bom_sparepart.product_id:
                if bom_sparepart._fields["product_id"].comodel_name == "product.product":
                    return bom_sparepart.product_id

        return self.env["product.product"].browse()

    
    
    def action_qty_minus(self):
        for line in self:
            line.qty = max(0.0, (line.qty or 0.0) - 1.0)

    def action_qty_plus(self):
        for line in self:
            line.qty = (line.qty or 0.0) + 1.0

    # ---------------------------------------------------------
    # Helper: domain spare_part_id (product.product)
    # ---------------------------------------------------------
    def _set_sparepart_domain(self):
        self.ensure_one()

        if self.machine_bom_id and self.machine_bom_id.spare_part_id:
            prod = self._bom_to_product(self.machine_bom_id.spare_part_id)
            return [("id", "=", prod.id)] if prod else [("id", "=", 0)]

        if self.part_id:
            if "product_ids" in self.part_id._fields:
                return [("id", "in", self.part_id.product_ids.ids)]
            return []

        return []

    # ---------------------------------------------------------
    # Onchange: spare_part_id -> isi detail dari product
    # ---------------------------------------------------------
    @api.onchange("spare_part_id")
    def _onchange_spare_part_id(self):
        for rec in self:
            if rec.spare_part_id:
                rec.sku = rec.spare_part_id.default_code or ""
                rec.specification = (
                    rec.spare_part_id.description_sale
                    or rec.spare_part_id.description
                    or ""
                )
            else:
                rec.specification = False
                rec.sku = False

    # ---------------------------------------------------------
    # Onchange: machine_bom_id
    # ---------------------------------------------------------
    @api.onchange("machine_bom_id")
    def _onchange_machine_bom_id(self):
        for rec in self:
            if rec.machine_bom_id:
                rec.part_id = rec.machine_bom_id.part_id
                prod = rec._bom_to_product(rec.machine_bom_id.spare_part_id)
                rec.spare_part_id = prod
                rec.specification = rec.machine_bom_id.specification or (
                    prod.description_sale or prod.description or ""
                )
                rec.sku = rec.machine_bom_id.sku or (prod.default_code or "")
            else:
                rec.part_id = False
                rec.spare_part_id = False
                rec.specification = False
                rec.sku = False

        return {"domain": {"spare_part_id": self[:1]._set_sparepart_domain()}}

    # ---------------------------------------------------------
    # Onchange: part_id
    # ---------------------------------------------------------
    @api.onchange("part_id")
    def _onchange_part_id(self):
        for rec in self:
            if rec.machine_bom_id:
                continue

            rec.spare_part_id = False
            rec.specification = False
            rec.sku = False

        return {"domain": {"spare_part_id": self[:1]._set_sparepart_domain()}}
