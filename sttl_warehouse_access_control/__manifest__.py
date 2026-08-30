# Manifest file of warehouse_access_control
{
    'name': 'Warehouse Access Management',
    'version' : '19.0.1.0',
    'depends': ['base', 'stock', 'stock_barcode'],
    'description': '''
       Warehouse Access Control
   ''',
    'data':[         
      'security/warehouse_group.xml',
      'security/warehouse_security.xml',      
      'views/res_users_views.xml',
      'views/stock_picking_type_views.xml',
    ],
    'images': ['static/description/banner.png'],
    'category': 'WMS',
    "author": "Silver Touch Technologies Limited",
    'installable': True,
    'application': False,
}
