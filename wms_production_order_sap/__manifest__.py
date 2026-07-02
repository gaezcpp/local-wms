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
    'license': 'LGPL-3',

    # any module necessary for this one to work correctly
    'depends': ['base', 'stock', 'wms_base_company', 'wms_inherit_stock_barcode', 'wms_base_warehouse'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
        'data/parameter.xml',
        'data/cron.xml',
        'data/sequence.xml',
        'reports/qr_production_order_sap.xml',
        'views/production_order_sap_views.xml',
        'views/stock_picking_views.xml',
        'views/stock_quant_views.xml',
        'views/stock_move_line_barcode_views.xml',
        'views/production_chronos_views.xml',
        'views/stock_lot_views.xml',
        'views/menuitem.xml',
    ],
    
    "assets": {
        "web.assets_backend": [
            "wms_production_order_sap/static/src/js/qr_production_order_sap.js",
            "wms_production_order_sap/static/src/xml/qr_production_order_sap_template.xml",
        ],
    },
}

