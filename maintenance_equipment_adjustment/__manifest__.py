# -*- coding: utf-8 -*-
{
    "name": "Maintenance Equipment Adjustment Fields",
    "summary": "Adds adjustment fields to Maintenance Equipment (auto number, business area, functional location, etc.)",
    "version": "19.0.1.0.0",
    "author": "Bayu Faturahman",
    "license": "LGPL-3",
    "category": "Maintenance",
    "depends": ["maintenance","product","hr_maintenance", "tagging_system"],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/ic_cron.xml",
        "views/business_area_views.xml",
        "views/maintenance_equipment_views.xml",
        "views/maintenance_equipment_tree_inherit.xml",
        "views/tagging_domain_inherit.xml",
    ],
    "application": False,
    "installable": True,
}
