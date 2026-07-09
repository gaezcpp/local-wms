{
    'name': "Base Inherit Stock Barcode",

    'summary': "Custom Inherit Stock Barcode",

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
    'depends': ['base', 'mail', 'stock', 'stock_barcode', 'wms_base_warehouse'],
    
    # always loaded
    'data': [
        'data/parameter.xml',
        'data/cron.xml',
        'data/sequence.xml',
        'security/ir.model.access.csv',
        'security/security.xml',
        'wizards/sloc_barcode_views.xml',
        'wizards/quality_quantity_backorder_views.xml',
        'views/product_template_views.xml',
        'views/stock_package_views.xml',
        'views/stock_picking_views.xml',
        'views/stock_quant_views.xml',
        'views/stock_lot_views.xml',
        'views/stock_move_line_barcode_views.xml',
        'views/stock_move_line_views.xml',
        'views/stock_inventory_adjustment_views.xml',
        'views/stock_move_views.xml',
        'views/daily_cycle_count_views.xml',
        'views/menuitem.xml',
    ],
    
    "assets": {
        "web.assets_backend": [
            "wms_inherit_stock_barcode/static/src/css/global_smart_button.css",
            "wms_inherit_stock_barcode/static/src/js/barcode_pickimg_model_patch.js",
            "wms_inherit_stock_barcode/static/src/js/digipad_patch.js",
            "wms_inherit_stock_barcode/static/src/js/barcode_auto_fill.js",
            "wms_inherit_stock_barcode/static/src/js/main_patch.js",
            "wms_inherit_stock_barcode/static/src/js/sloc_packaging.js",
            "wms_inherit_stock_barcode/static/src/js/quality_quantity_backorder.js",
            "wms_inherit_stock_barcode/static/src/js/duplicate_product.js",
            "wms_inherit_stock_barcode/static/src/js/daily_cycle_count.js",
            "wms_inherit_stock_barcode/static/src/js/full_pallet_button.js",
            "wms_inherit_stock_barcode/static/src/js/package_line_component_patch.js",
            'wms_inherit_stock_barcode/static/src/xml/stock_barcode_menu.xml',
            'wms_inherit_stock_barcode/static/src/xml/sloc_packaging_views.xml',
            'wms_inherit_stock_barcode/static/src/xml/barcode_line_component_views.xml',
            'wms_inherit_stock_barcode/static/src/xml/quality_quantity_backorder_views.xml',
            'wms_inherit_stock_barcode/static/src/xml/confirm_inventory_adjustment_views.xml',
        ],
    },

}

