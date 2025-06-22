from django.utils import timezone

class DamascusTimezoneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        timezone.activate('Asia/Damascus')
        response = self.get_response(request)
        timezone.deactivate()
        return response