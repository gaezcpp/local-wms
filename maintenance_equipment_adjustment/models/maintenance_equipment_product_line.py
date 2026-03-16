from odoo import fields, models, api, _

class MaintenanceEquipmentProductLine(models.Model):
    _name = "maintenance.equipment.product.line"
    _description = "Maintenance Equipment Product Line"
    _order = "id desc"

    equipment_id = fields.Many2one(
        "maintenance.equipment",
        string="Equipment",
        required=True,
        ondelete="cascade",
    )

    # FIELD LAMA (biarin dulu untuk jaga data)
    product_id = fields.Many2one(
        "product.product",
        string="Product (Legacy)",
        domain=[("sale_ok", "=", True)],
    )

    # FIELD BARU
    spare_part_id = fields.Many2one(
        "tagging.spare_part",
        string="Spare Part",
        ondelete="restrict",
    )

    # Multi-company safe (mengikuti equipment)
    company_id = fields.Many2one(
        related="equipment_id.company_id",
        store=True,
        readonly=True,
    )

    # Domain spare part per plant/company
    # (kalau tagging.spare_part sudah punya company_id)
    # catatan: domain python static gak bisa pakai field, jadi pakai domain di view XML atau pakai domain string di field:
    # domain="[('company_id', '=', company_id)]" -> lebih aman taruh di XML
    # di sini kita biarkan kosong, nanti saya kasih snippet XML

    sku = fields.Char(
        string="SKU",
        compute="_compute_spare_part_info",
        store=True,
        readonly=True,
    )
    

    product_name = fields.Char(
        string="Name",
        compute="_compute_spare_part_info",
        store=False,
        readonly=True,
    )

    qty = fields.Float(string="Qty", default=1.0)
    note = fields.Char(string="Note")

    
    _sql_constraints = [
    (
        "uniq_equipment_spare_part",
        "unique(equipment_id, spare_part_id)",
        "Spare part already exists for this equipment.",
    )
]
    @api.depends("spare_part_id", "spare_part_id.sku", "spare_part_id.product_id")
    def _compute_spare_part_info(self):
        for rec in self:
            rec.sku = rec.spare_part_id.sku or False
            rec.product_name = rec.spare_part_id.product_id.display_name if rec.spare_part_id else False

    def action_migrate_legacy_product_to_spare_part(self):
        """
        Jalankan sekali (manual) setelah update module:
        - mapping product_id lama -> spare_part_id berdasarkan tagging.spare_part.product_id
        """
        SparePart = self.env["tagging.spare_part"].sudo()
        for rec in self.search([("spare_part_id", "=", False), ("product_id", "!=", False)]):
            sp = SparePart.search([
                ("product_id", "=", rec.product_id.id),
                ("company_id", "=", rec.company_id.id),
            ], limit=1)
            if not sp:
                # fallback kalau sparepart tidak company-specific
                sp = SparePart.search([("product_id", "=", rec.product_id.id)], limit=1)

            if sp:
                rec.spare_part_id = sp.id
