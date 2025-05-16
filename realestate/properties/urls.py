from django.urls import path
from .views import PropertyListView,PropertyDetailView,AddPropertyView,EditPropertyView, EditImageCaptionView,DeleteImageCaptionView
from .views import AddFacilityView,RemoveFacilityView,AddPropertyImageView,DeletePropertyImageView
from .views import AddToFavoritesView,RemoveFromFavoritesView,ListFavoritePropertiesView
urlpatterns = [
    path('', PropertyListView.as_view(), name='property-list'),
    path('<int:property_id>/',PropertyDetailView.as_view(),name='property-detail'),
    path('add/', AddPropertyView.as_view(), name='add-property'),
    path('<int:property_id>/edit/', EditPropertyView.as_view(), name='edit-property'),
    path('<int:property_id>/facilities/add/', AddFacilityView.as_view(), name='add-facility'),
    path('<int:property_id>/facilities/<int:facility_id>/remove/', RemoveFacilityView.as_view(), name='remove-facility'),
    path('<int:property_id>/images/<int:image_id>/delete/', DeletePropertyImageView.as_view(), name='delete-property-image'),
    path('<int:property_id>/images/add/', AddPropertyImageView.as_view(), name='add-property-image'),
    path(
        '<int:property_id>/images/<int:image_id>/edit-caption/',
        EditImageCaptionView.as_view(),
        name='edit-image-caption'
    ),
    path(
        '<int:property_id>/images/<int:image_id>/delete-caption/',
        DeleteImageCaptionView.as_view(),
        name='delete-image-caption'
    ),
    path('<int:property_id>/favorite/', AddToFavoritesView.as_view(), name='add-to-favorites'),
    path('<int:property_id>/unfavorite/', RemoveFromFavoritesView.as_view(), name='remove-from-favorites'),
    path('favorites/', ListFavoritePropertiesView.as_view(), name='list-favorites'),
    
    
    
]