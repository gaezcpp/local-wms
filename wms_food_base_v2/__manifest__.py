{
    'name': "WMS FOOD BASE V2",

    'summary': "Short (1 phrase/line) summary of the module's purpose",

    'description': """
Long description of module's purpose
    """,

    'author': "Mr Gaez",
    'website': "https://www.cpp.co.id",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'FOOD',
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',
    'installable': True,
    'application': True,

    # any module necessary for this one to work correctly
    'depends': ['base', 'stock', 'mail'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
        'data/parameter.xml',
        'data/cron.xml',
        'views/product_template_views.xml',
        'views/uom_uom_views.xml',
        'views/food_master_qr_views.xml',
        'views/food_production_group_views.xml',
        'views/food_production_line_views.xml',
        'views/food_production_order_views.xml',
        'views/food_production_shift_views.xml',
        'views/food_storage_location_views.xml',
        'views/menu.xml',
    ],
}
