# Tagging System (Odoo 19) - Website + Internal Maintenance

## Website (for submit)
- URL: /tagging (login required: internal + portal)
- Submit saves to tagging.record + photos to ir.attachment
- Redirects back to /tagging?success=1 and shows success modal

## Internal (maintenance)
- Menu: Tagging System
  - Dashboard / Open Tagging -> opens Tagging List (tree/form/graph/pivot)
- Filters: Status, Plant, Category System, PIC
- Status workflow: Open / Postponed / Closed (buttons in list & form)

## Install
1) Put folder in your custom addons path (e.g. addons_custom/tagging_system)
2) Update addons_path in odoo.conf:
   addons_path = odoo/addons,addons_custom
3) Update Apps list and install module.

Tip: If you already installed v1, upgrade the module.
