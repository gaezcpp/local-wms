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
    'license': 'LGPL-3',

    # any module necessary for this one to work correctly
    'depends': ['base', 'mail', 'stock', 'wms_base_company'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'wizard/unpack_stock_package_views.xml',
        'data/parameter.xml',
        'data/cron.xml',
        'views/production_line_views.xml',
        'views/production_shift_views.xml',
        'views/production_code_views.xml',
        'views/production_group_views.xml',
        'views/inh_stock_package_views.xml',
        'views/stock_picking_type_views.xml',
        'views/stock_picking_views.xml',
        'views/stock_putaway_rule_views.xml',
        'views/stock_move_line_views.xml',
        'views/stock_move_line_gr_views.xml',
        'views/uom_uom_views.xml',
        'views/stock_location_views.xml',
        'views/stock_sap_views.xml',
        'views/product_packaging_views.xml',
        'views/storage_location_views.xml',
        'views/stock_lot_views.xml',
        'views/menuitem.xml',
    ],
}

