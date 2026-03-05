import django_filters
from .models import InstallationJob, VehicleMake


class InstallationJobFilter(django_filters.FilterSet):
    # Vehicle filters
    make = django_filters.CharFilter(field_name='vehicle_make__slug')
    model = django_filters.CharFilter(field_name='vehicle_model', lookup_expr='icontains')
    year = django_filters.NumberFilter(field_name='vehicle_year')
    year_from = django_filters.NumberFilter(field_name='vehicle_year', lookup_expr='gte')
    year_to = django_filters.NumberFilter(field_name='vehicle_year', lookup_expr='lte')

    # Job filters
    status = django_filters.ChoiceFilter(choices=InstallationJob.STATUS_CHOICES)
    is_featured = django_filters.BooleanFilter(field_name='is_featured')
    technician = django_filters.CharFilter(field_name='technician', lookup_expr='icontains')

    # Date filters
    date_from = django_filters.DateFilter(field_name='job_date', lookup_expr='gte')
    date_to = django_filters.DateFilter(field_name='job_date', lookup_expr='lte')

    # Item category filter — jobs that include a certain type of install
    has_item_category = django_filters.CharFilter(method='filter_by_item_category')

    class Meta:
        model = InstallationJob
        fields = ['status', 'is_featured', 'vehicle_make', 'vehicle_year']

    def filter_by_item_category(self, queryset, name, value):
        """Filter jobs that contain at least one item of the given category"""
        return queryset.filter(installed_items__category=value).distinct()