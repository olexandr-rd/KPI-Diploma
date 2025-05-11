# monitoring/middleware.py

class BrokenPipeErrorMiddleware:
    """Middleware to handle broken pipe errors gracefully"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            response = self.get_response(request)
            return response
        except BrokenPipeError:
            # Just ignore this error and return an empty response
            from django.http import HttpResponse
            return HttpResponse('')
