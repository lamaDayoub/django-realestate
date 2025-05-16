from rest_framework.filters import SearchFilter

class CaseInsensitiveSearchFilter(SearchFilter):
    """
    Custom SearchFilter to perform case-insensitive searches.
    """
    def construct_search(self, field_name, lookup_expr=None):
        # Use 'icontains' for case-insensitive search
        return f"{field_name}__icontains"