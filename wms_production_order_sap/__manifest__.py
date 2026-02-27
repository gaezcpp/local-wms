{
    'name': "WMS Production Order",

    'summary': "Production Order SAP",

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

    # any module necessary for this one to work correctly
    'depends': ['base', 'stock'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'views/production_order_sap_views.xml',
        'views/stock_picking_views.xml',
        'views/menuitem.xml',
    ],
}

