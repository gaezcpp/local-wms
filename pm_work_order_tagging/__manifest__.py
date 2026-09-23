{
    'name': "PM Work Order",

    'summary': "Work Order",

    'description': """
Handover task dari Bayu (tagging dan maintenance)
    """,

    'author': "MrGaez",
    'website': "https://www.cpp.co.id",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'PM',
    'version': '19.0.1.2.2',

    # any module necessary for this one to work correctly
    'depends': ['base', 'maintenance', 'wms_base_company', 'tagging_system'],
    'license': 'LGPL-3',

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
        'security/tagging_work_order_security.xml',
        'wizards/pm_notification_wizard_views.xml',
        'data/sequence.xml',
        'data/parameter.xml',
        'data/cron.xml',
        'data/mail_template.xml',
        'data/pm_notification_mail_template.xml',
        # 'data/server_action.xml',
        'views/pm_work_order_views.xml',
        'views/tagging_record_views.xml',
        'views/tagging_type_notification_views.xml',
        'views/pm_analysis_views.xml',
        'views/zmo_report_views.xml',
        'views/menuitem.xml',
    ],
}
