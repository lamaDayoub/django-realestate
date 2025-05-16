from rest_framework.permissions import BasePermission

class IsSeller(BasePermission):
    """
    Custom permission to allow only users in seller mode.
    """
    message = "You must be in seller mode to perform this action."

    def has_permission(self, request, view):
        return request.user.is_authenticated and getattr(request.user, 'is_seller', False)