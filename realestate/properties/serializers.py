from rest_framework import serializers
from .models import Property, PropertyImage,Facility

class CoordinateValidationMixin:
    def validate_latitude(self, value):
        if not (-90 <= value <= 90):
            raise serializers.ValidationError("Latitude must be between -90 and 90.")
        return value

    def validate_longitude(self, value):
        if not (-180 <= value <= 180):
            raise serializers.ValidationError("Longitude must be between -180 and 180.")
        return value
    
    
class PropertySerializer(CoordinateValidationMixin,serializers.ModelSerializer):
    main_photo = serializers.SerializerMethodField()

    class Meta:
        model = Property
        fields = [
            'id',
            'owner',
            'ptype',
            'city',
            'number_of_rooms',
            'area',
            'price',
            'is_for_rent',
            'latitude',
            'longitude',
            'main_photo',  # Include the main photo URL
        ]
        
    def get_main_photo(self, obj):
        # Get the first image for the property, if any
        first_image = obj.images.first()
        return first_image.image.url if first_image else None
    
      

class PropertyImageSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = PropertyImage
        fields = ['id', 'image', 'image_url', 'caption']
        read_only_fields = ['property']

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get('request')
            return request.build_absolute_uri(obj.image.url)
        return None

    def validate(self, data):
        # Ensure property_id is provided during creation
        property_id = self.context.get('property_id')
        if property_id is None and self.instance is None:  # Only enforce during creation
            raise serializers.ValidationError("Property ID is required.")

        # Ensure the image file is provided during creation
        if self.instance is None and 'image' not in data:  # Only enforce during creation
            raise serializers.ValidationError("Image file is required.")
        try:
            property_instance = Property.objects.get(id=property_id)
        except Property.DoesNotExist:
            raise serializers.ValidationError("Invalid property ID.")

        # Ensure the property doesn't exceed the maximum number of images
        if property_instance.images.count() >= 10:
            raise serializers.ValidationError("A property cannot have more than 10 images.")

       

        return data
    
class FacilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Facility
        fields = ['id', 'name']

class AddFacilitySerializer(serializers.Serializer):
    facility_id = serializers.IntegerField(required=True)

    def validate_facility_id(self, value):
        """
        Validate that the facility with the given ID exists.
        """
        try:
            Facility.objects.get(id=value)
        except Facility.DoesNotExist:
            raise serializers.ValidationError("Facility with this ID does not exist.")
        return value
    
class PropertyDetailSerializer(CoordinateValidationMixin,serializers.ModelSerializer):
    facilities = FacilitySerializer(many=True, read_only=True)
    images = PropertyImageSerializer(many=True, read_only=True)

    class Meta:
        model = Property
        fields = [
            'id',
            'owner',
            'ptype',
            'city',
            'number_of_rooms',
            'area',
            'location_text',
            'price',
            'is_for_rent',
            'details',
            'latitude',
            'longitude',
            'facilities',
            'images',
        ]