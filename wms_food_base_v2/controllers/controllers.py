# from odoo import http


# class WmsFoodBaseV2(http.Controller):
#     @http.route('/wms_food_base_v2/wms_food_base_v2', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/wms_food_base_v2/wms_food_base_v2/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('wms_food_base_v2.listing', {
#             'root': '/wms_food_base_v2/wms_food_base_v2',
#             'objects': http.request.env['wms_food_base_v2.wms_food_base_v2'].search([]),
#         })

#     @http.route('/wms_food_base_v2/wms_food_base_v2/objects/<model("wms_food_base_v2.wms_food_base_v2"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('wms_food_base_v2.object', {
#             'object': obj
#         })

