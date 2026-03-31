{
    'name': "Sale Order SAP",

    'summary': "WMS Sale Order SAP",

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
    'depends': ['base', 'sale', 'sale_management', 'stock', 'wms_base_company'],

    # always loaded
    'data': [
        'data/parameter.xml',
        'data/cron.xml',
        'views/sale_order_views.xml',
    ],
}

