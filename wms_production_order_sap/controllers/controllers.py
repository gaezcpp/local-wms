# from odoo import http


# class WmsProductionOrderSap(http.Controller):
#     @http.route('/wms_production_order_sap/wms_production_order_sap', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/wms_production_order_sap/wms_production_order_sap/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('wms_production_order_sap.listing', {
#             'root': '/wms_production_order_sap/wms_production_order_sap',
#             'objects': http.request.env['wms_production_order_sap.wms_production_order_sap'].search([]),
#         })

#     @http.route('/wms_production_order_sap/wms_production_order_sap/objects/<model("wms_production_order_sap.wms_production_order_sap"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('wms_production_order_sap.object', {
#             'object': obj
#         })

