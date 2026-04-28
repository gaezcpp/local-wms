{
    'name': "Debt Management",

    'summary': "Debt Management",

    'description': """
Long description of module's purpose
    """,

    'author': "Mr Gaez",
    'website': "https://www.yourcompany.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Uncategorized',
    'version': '0.1',
    'license' : 'LGPL-3',

    # any module necessary for this one to work correctly
    'depends': ['base', 'mail'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'data/sequence.xml',
        'reports/debt_management_report_views.xml',
        'views/debt_management_views.xml',
        'views/debt_management_line_views.xml',
        'views/debt_type_views.xml',
        'views/debt_customer_views.xml',
        'views/menuitem.xml',
    ],
    "icon": "/wms_production_order_sap/static/description/icon.png",
}

