{
    'name': "Quality Packages",

    'summary': "Ganti status packages",

    'description': """
Long description of module's purpose
    """,

    'author': "Mr Gaez",
    'website': "https://www.cpp.co.id",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'WMS',
    'version': '0.1',
    'license': 'LGPL-3',

    # any module necessary for this one to work correctly
    'depends': ['base', 'stock', 'wms_production_order_sap'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
        'data/sequence.xml',
        'wizards/package_wizards_views.xml',
        'wizards/quality_packages_wizard_views.xml',
        'views/quality_packages_views.xml',
        'views/quality_packages_summary_views.xml',
        'views/category_quality_packages_views.xml',
        'views/sap_aft_views.xml',
        'views/stock_package_views.xml',
        'views/action_quality_packages_views.xml',
        'views/menuitem.xml',
    ],
}

