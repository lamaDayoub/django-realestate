from django.db import models
from django.contrib.auth import get_user_model

from django.core.validators import MinValueValidator

User = get_user_model()
def property_directory_path(instance, filename):
    """
    Define the upload path for property images.
    Example: propertiesphotos/property_1/photo.jpg
    """
    return f'propertiesphotos/property_{instance.property.id}/{filename}'

class Facility(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name
    
class Property(models.Model):
    PROPERTY_TYPES = [
        ('flat', 'Flat'),
        ('villa', 'Villa'),
        ('house', 'House'),
    ]

    owner = models.ForeignKey('users.User', on_delete=models.CASCADE, related_name='properties')
    ptype = models.CharField(max_length=10, choices=PROPERTY_TYPES)
    city = models.CharField(max_length=100, db_index=True)
    number_of_rooms = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    area = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(10)])  # e.g., 120.50 sqm
    location_text = models.TextField()
    price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    is_for_rent = models.BooleanField(default=False, db_index=True)  # True if for rent, False if for sale
    details = models.TextField(blank=True, null=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)  # For OpenStreetMap coordinates
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)  # For OpenStreetMap coordinates
    facilities = models.ManyToManyField(
        Facility,
        through='PropertyFacility',
        related_name='properties'
    )
    
    def __str__(self):
        return f"{self.ptype} in {self.city} ({'For Rent' if self.is_for_rent else 'For Sale'})"
    
    
class PropertyImage(models.Model):
    property = models.ForeignKey('Property', on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to=property_directory_path)
    caption = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"Image for {self.property}"
    

class PropertyFacility(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='property_facilities')
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('property', 'facility')

    def __str__(self):
        return f"{self.facility} for {self.property}"

class FavoriteProperty(models.Model):
    user = models.ForeignKey('users.User', on_delete=models.CASCADE, related_name='favorite_property_relations')
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='favorited_by_relations')

    class Meta:
        unique_together = ('user', 'property')

    def __str__(self):
        return f"{self.user}'s favorite: {self.property}"