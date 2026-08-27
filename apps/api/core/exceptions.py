from rest_framework.views import exception_handler
from rest_framework.exceptions import APIException


class Conflict(APIException):
    status_code = 409
    default_detail = "Conflict."
    default_code = "conflict"


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None:
        response.data = {
            "error": {
                "status": response.status_code,
                "code": getattr(exc, "default_code", "request_error"),
                "detail": response.data,
            }
        }
    return response
