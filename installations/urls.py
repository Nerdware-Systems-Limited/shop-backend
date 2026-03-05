from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    VehicleMakeViewSet,
    InstallationJobViewSet,
    InstallationImageViewSet,
    InstalledItemViewSet,
)

router = DefaultRouter()
router.register(r'vehicle-makes', VehicleMakeViewSet, basename='vehiclemake')
router.register(r'jobs', InstallationJobViewSet, basename='installation-job')
router.register(r'images', InstallationImageViewSet, basename='installation-image')
router.register(r'items', InstalledItemViewSet, basename='installed-item')

urlpatterns = [
    path('', include(router.urls)),
]