Maintenance Equipment Adjustment Fields (Odoo 19)

What it does
- Adds adjustment fields to maintenance.equipment:
  - No. Equipment (equipment_no) : auto generated via ir.sequence (maintenance.equipment.no)
  - Abc Indc (abc_indc) : free text
  - Maint Plant (maint_plant) : related from company code (update related field path)
  - Business Area (business_area_id) : dropdown with create (master model)
  - Superord.Equip. (superord_equip) : free text
  - Functional Loc (functional_loc_tagging_id) : dropdown from barcode.tagging, no create in view

IMPORTANT SETUP
1) Update the related field path for Maint Plant:
   In models/maintenance_equipment.py, change:
     related="company_id.x_company_code"
   to whatever field you use for company code on res.company.

2) This module expects the model `barcode.tagging` to exist.
   If your barcode tagging module has a different name/model, adjust the comodel_name accordingly.

If installation fails due to missing view external IDs:
- Update inherit_id references in views/maintenance_equipment_views.xml.
