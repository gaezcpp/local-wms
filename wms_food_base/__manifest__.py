{
    'name': "WMS Food Base",
    'summary': "Base Untuk FOOD",
    'description': """
FOOD/FEED branching for warehouse operations.
All current development targets FEED; FOOD operations are blocked
until FOOD-specific logic is implemented.
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
    ],
    'data': [
        'views/res_company_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
