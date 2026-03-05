from rest_framework import permissions


class IsAdminOrReadOnly(permissions.BasePermission):
    """Staff can write; anyone can read (public jobs only filtered in views)"""
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_staff