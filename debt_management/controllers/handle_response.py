import werkzeug.wrappers
import json

def handle_response(success=True, message='', data=None):
    return werkzeug.wrappers.Response(
        status=200,
        content_type='application/json',
        response=json.dumps({
            'success': success,
            'message': message,
            'data': data,
        }),
    )