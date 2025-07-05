from rest_framework import serializers
from .models import Property, PropertyImage,Facility, Rating

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
            'active',
            'ptype',
            'city',
            'number_of_rooms',
            'bathrooms',
            'area',
            'price',
            'is_for_rent',
            'latitude',
            'longitude',
            'rating',
            'main_photo',  # Include the main photo URL
        ]
        extra_kwargs = {
            'owner': {'read_only': True},
            'rating':{'read_only': True},
        }
    def validate(self, data):
        # Check for existing similar properties
        existing = Property.objects.filter(
            owner=self.context['request'].user,
            ptype=data.get('ptype'),
            city=data.get('city'),
            area=data.get('area'),
            price=data.get('price'),
            active=data.get('active'),
            number_of_rooms=data.get('number_of_rooms'),
            bathrooms=data.get('bathrooms'),
            is_for_rent=data.get('is_for_rent'),
            latitude=data.get('latitude'),
            longitude=data.get('longitude'),
            
        ).exists()
        
        if existing:
            raise serializers.ValidationError(
                "You already have a similar property listed with these exact details."
            )
        return data
        
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
            'active',
            'owner',
            'ptype',
            'city',
            'number_of_rooms',
            'bathrooms',
            'area',
            'location_text',
            'price',
            'rating',
            'is_for_rent',
            'details',
            'latitude',
            'longitude',
            'facilities',
            'images',
            
        ]
        
class PropertyRatingInputSerializer(serializers.Serializer):
    """
    Serializer for accepting rating input (value and optional comment).
    """
    value = serializers.IntegerField(
        min_value=1,
        max_value=5,
        required=True,
        help_text="The rating value (1-5 stars)."
    )
    

    def validate(self, data):
        # Context will contain 'request' and 'property' instance from the view
        request_user = self.context['request'].user
        property_instance = self.context['property']

        # Ensure user is not the owner of the property
        if property_instance.owner == request_user:
            raise serializers.ValidationError("You cannot rate your own property.")


        return data
    
class RatingSerializer(serializers.ModelSerializer): # <--- NEW CLASS
    """
    Serializer for creating and listing individual property ratings.
    """
    user_id = serializers.ReadOnlyField(source='user.id') # Read-only ID of the user who rated
    user_email = serializers.ReadOnlyField(source='user.email') # Read-only email of the user who rated
    # No comment, created_at, updated_at fields here as per simplified Rating model

    class Meta:
        model = Rating
        fields = ['id', 'user_id', 'user_email', 'property', 'value'] # No comment field
        read_only_fields = ['id', 'user_id', 'user_email'] # property is write_only in views context
        extra_kwargs = {
            'property': {'write_only': True} # Property ID is sent in the URL, not body
        }

    def create(self, validated_data):
        # The 'user' and 'property' instances will be provided by the view
        return Rating.objects.create(**validated_data)

    def validate(self, data):
        # Context will contain 'request' and 'property_instance' from the view
        request_user = self.context['request'].user
        property_instance = self.context['property_instance'] # Renamed context key for clarity

        # Enforce "user cannot rate their own property"
        if property_instance.owner == request_user:
            raise serializers.ValidationError("You cannot rate your own property.")

        # Enforce "rate once" using unique_together constraint on Rating model
        # This check is technically redundant as the DB will enforce unique_together,
        # but it provides a cleaner error message to the user.
        if Rating.objects.filter(user=request_user, property=property_instance).exists():
            raise serializers.ValidationError("You have already rated this property.")

        return data