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

    # any module necessary for this one to work correctly
    'depends': ['base', 'stock', 'stock_barcode'],
    
    "assets": {
        "web.assets_backend": [
            "wms_inherit_stock_barcode/static/src/js/barcode_line_uom_conversion.js",
            "wms_inherit_stock_barcode/static/src/xml/barcode_line_uom_conversion.xml",
        ],
    },

    # always loaded
    'data': [
        # 'views/views.xml',
        # 'views/templates.xml',
    ],
}

