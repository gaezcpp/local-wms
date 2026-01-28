{
    'name': "Base Warehouse Custom",

    'summary': "Short (1 phrase/line) summary of the module's purpose",

    'description': """
Long description of module's purpose
    """,

    'author': "MrGaez",
    'website': "https://www.cpp.co.id",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'WMS',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['base', 'stock', 'product'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'wizard/unpack_stock_package_views.xml',
        'views/inh_stock_package_views.xml',
    ],
}

