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
    'version': '19.0.1.0.0',
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
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
