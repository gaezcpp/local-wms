{
    'name': "PM Work Order",

    'summary': "Work Order",

    'description': """
Handover task dari Bayu (tagging dan maintenance)
    """,

    'author': "MrGaez",
    'website': "https://www.cpp.co.id",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'PM',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['base', 'maintenance', 'wms_base_company', 'tagging_system'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'data/sequence.xml',
        'data/parameter.xml',
        'data/cron.xml',
        'views/pm_work_order_views.xml',
        'views/tagging_record_views.xml',
        'views/menuitem.xml',
    ],
}

