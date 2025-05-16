from django.contrib import admin
from .models import Property,PropertyImage,Facility,FavoriteProperty,PropertyFacility
# Register your models here.
admin.site.register(Property)
admin.site.register(PropertyFacility)
admin.site.register(PropertyImage)
admin.site.register(FavoriteProperty)
admin.site.register(Facility)
