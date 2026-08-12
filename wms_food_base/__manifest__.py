{
    'name': "WMS Food Base",
    'summary': "Base Untuk FOOD",
    'description': """
Defines company.wms_type (FOOD/FEED). All current FEED-specific
customizations (wms_base_warehouse, wms_inherit_stock_barcode,
wms_production_order_sap, wms_sale_order_sap) are only meant to apply
to FEED companies. This module depends on all of them so it always
loads last, then re-overrides every method they customize: when
company_id.wms_type == 'FOOD' it jumps straight past all of those
custom layers into native Odoo behavior; otherwise it calls super()
normally and the existing FEED logic runs unchanged.
    """,
    'author': "Mr Gaez",
    'website': "https://www.cpp.co.id",
    'category': 'WMS',
    'version': '19.0.1.2.0',
    'depends': [
        'base',
        'stock',
        'wms_base_warehouse',
        'wms_inherit_stock_barcode',
        'wms_production_order_sap',
        'wms_sale_order_sap',
    ],
    'data': [
        'views/res_company_views.xml',
        'views/stock_picking_views.xml',
        'views/stock_move_views.xml',
        'views/stock_move_line_views.xml',
        'views/stock_move_line_barcode_views.xml',
        'views/stock_quant_views.xml',
        'views/stock_lot_views.xml',
        'views/stock_package_views.xml',
        'views/stock_location_views.xml',
        'views/stock_picking_type_views.xml',
        'views/product_template_views.xml',
        'views/uom_uom_views.xml',
    ],
    # JS/OWL barcode app bypasses (Phase 4). Every file here must load AFTER
    # its wms_inherit_stock_barcode counterpart so its `patch()`/QWeb
    # `t-inherit` calls apply on top of FEED's (see
    # static/src/js/food_barcode_utils.js for why a plain `super.x()` alone
    # cannot reach native behaviour here, and how each file resolves it).
    'assets': {
        'web.assets_backend': [
            'wms_food_base/static/src/js/food_barcode_utils.js',
            'wms_food_base/static/src/js/barcode_pickimg_model_patch.js',
            'wms_food_base/static/src/js/barcode_quant_model_patch.js',
            'wms_food_base/static/src/js/digipad_patch.js',
            'wms_food_base/static/src/js/package_line_component_patch.js',
            'wms_food_base/static/src/xml/barcode_line_component_views.xml',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
