{
    "name": "Tagging System (Website + Internal Maintenance)",
    "version": "1.1.0",
    "category": "Operations",
    "summary": "Website tagging form and internal maintenance (list, filters, dashboard charts)",
    "author": "Bayu Faturahman",
    "license": "LGPL-3",
    "depends": [
        "base",
        "web",
        "website",
        "mail",
        "maintenance",
        "product",
        ],
    "data": [
        # Security first
        "security/security.xml",
        "security/ir.model.access.csv",

        # Sequences
        "data/sequence.xml",
        "data/ir_cron.xml",
        "data/ir_cron_sycn_master_data.xml",
        "data/barcode_tagging_sequence.xml",

        # Masters / Reference
        "views/category_problem_view.xml",
        "views/barcode_tagging_views.xml",
        "views/barcode_tagging_actions.xml",

        # PIC / Department / BU 
        "views/tagging_pic_action.xml",
        "views/tagging_pic_views.xml",

        # Main tagging backend + records
        "views/tagging_backend.xml",
        "views/tagging_master_equipment.xml",

        # Wizards
        "views/tagging_record_close_wizard.xml",
        "views/tagging_wo_sparepart_wizard_views.xml",
        "views/tagging_bom_import_wizard_views.xml",
        
        #company
        "views/res_company_view.xml",

        # Dashboard action
        "views/tagging_dashboard_action.xml",

        # Website templates
        "views_website/templates.xml",

        # Menus MUST be last (refer actions)
        "views/tagging_master_menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "tagging_system/static/lib/chartjs/chart.umd.min.js",
            "tagging_system/static/lib/chartjs/chartjs-chart-treemap.min.js",
            "tagging_system/static/src/components/tagging_dashboard/tagging_dashboard.js",
            "tagging_system/static/src/components/tagging_dashboard/tagging_dashboard.scss",
            "tagging_system/static/src/components/tagging_dashboard/tagging_dashboard.xml",
        ],
    },
    "installable": True,
    "application": True,
}
