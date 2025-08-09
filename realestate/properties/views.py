from rest_framework.generics import ListAPIView
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from .models import Property,PropertyImage,Facility,PropertyFacility, FavoriteProperty
from .serializers import RatingSerializer , PropertySerializer,PropertyDetailSerializer,PropertyImageSerializer,FacilitySerializer,AddFacilitySerializer
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from .permissions import IsSeller
from rest_framework.parsers import MultiPartParser
from .filters import CaseInsensitiveSearchFilter
import os
from django.db.models import Q ,Avg, F
from django.conf import settings
from rest_framework import generics
from django.contrib.contenttypes.models import ContentType 
from notifications.models import Notification
from notifications.tasks import dispatch_notification_task
from django.db.models.signals import post_save
from drf_yasg.openapi import Schema, TYPE_OBJECT, TYPE_ARRAY, TYPE_INTEGER, TYPE_STRING, FORMAT_URI, TYPE_NUMBER, TYPE_BOOLEAN
class PropertyListView(ListAPIView):
    """
    Advanced property search endpoint with flexible filtering options.
    Supports filtering by authenticated owner and various query parameters.
    """
    serializer_class = PropertySerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]

    filterset_fields = {
        'is_for_rent': ['exact'],
        'active': ['exact'],
    }

    search_fields = ['city', 'location_text']
    ordering_fields = ['price', 'area', 'number_of_rooms', 'bathrooms']
    ordering = ['-id'] # Default ordering
    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        If 'mine=true' is in query params, require IsAuthenticated and IsSeller.
        Otherwise, allow any.
        """
        mine_filter = self.request.query_params.get('mine', 'false').lower()
        if mine_filter == 'true':
            # If 'mine=true', user must be authenticated AND be a seller (owner)
            return [IsAuthenticated(), IsSeller()] # <--- Changed permission logic
        else:
            # Otherwise, allow any user to see general public listings
            return [AllowAny()]
    def get_queryset(self):
        """
        This view now returns a queryset filtered by 'owner=me' or all active properties.
        """
        user = self.request.user
        # Get the 'mine' query parameter
        mine_filter = self.request.query_params.get('mine', 'false')

        # --- User's custom logic implemented here ---
        if mine_filter.lower() == 'true':
            # Return only properties owned by the authenticated user
            # We can assume the user is authenticated due to permission_classes = [IsAuthenticated]
            queryset = Property.objects.filter(owner=user)
        else:
            # Return all active properties for the general listing
            queryset = Property.objects.filter(active=True)
        # --- End custom logic ---

        # Prefetch images for efficiency to avoid N+1 queries
        return queryset.prefetch_related('images')

    def filter_queryset(self, queryset):
        """
        This custom method applies the more complex comma-separated filters
        on top of the base queryset from get_queryset.
        """
        # First, get the base queryset from `get_queryset` (which is already filtered by `owner` if applicable)
        queryset = super().filter_queryset(queryset)
        params = self.request.query_params

        # --- Custom filtering logic adapted from your original PropertyListView ---
        if 'types' in params:
            types = [t.strip().lower() for t in params['types'].split(',') if t.strip()]
            if types:
                queryset = queryset.filter(
                    Q(*[Q(ptype__iexact=type_name) for type_name in types], _connector=Q.OR)
                )

        if 'cities' in params:
            cities = [c.strip() for c in params['cities'].split(',') if c.strip()]
            if cities:
                queryset = queryset.filter(
                    Q(*[Q(city__iexact=city_name) for city_name in cities], _connector=Q.OR)
                )

        # Numeric range filters
        try:
            if 'min_price' in params:
                queryset = queryset.filter(price__gte=float(params['min_price']))
            if 'max_price' in params:
                queryset = queryset.filter(price__lte=float(params['max_price']))
            if 'min_area' in params:
                queryset = queryset.filter(area__gte=float(params['min_area']))
            if 'max_area' in params:
                queryset = queryset.filter(area__lte=float(params['max_area']))
            if 'min_rooms' in params:
                queryset = queryset.filter(number_of_rooms__gte=int(params['min_rooms']))
            if 'max_rooms' in params:
                queryset = queryset.filter(number_of_rooms__lte=int(params['max_rooms']))
            if 'min_bathrooms' in params:
                queryset = queryset.filter(bathrooms__gte=int(params['min_bathrooms']))
            if 'max_bathrooms' in params:
                queryset = queryset.filter(bathrooms__lte=int(params['max_bathrooms']))
        except (ValueError, TypeError):
            pass

        return queryset

    @swagger_auto_schema(
        operation_description="""
        ## Advanced Property Search

        Search properties with powerful filtering capabilities.
        All parameters are optional - combine them as needed.

        ### Filtering by Owner:
        - To see properties you own, use the `mine=true` parameter with a valid JWT token.

        ### Examples:
        1. All properties (unauthenticated): `/properties/`
        2. My villas in Damascus (authenticated): `/properties/?mine=true&types=villa&cities=damascus`
        3. All properties under $300k: `/properties/?max_price=300000`
        """,
        manual_parameters=[
            # --- NEW: Add the 'mine' parameter for Swagger documentation ---
            openapi.Parameter(
                'mine', 
                openapi.IN_QUERY, 
                description="Set to `true` to filter by properties owned by the authenticated user. Requires a JWT token.", 
                type=openapi.TYPE_BOOLEAN,
                required=False,
                default=False
            ),
            # --- END NEW ---
            openapi.Parameter('types', openapi.IN_QUERY, description="Comma-separated property types (flat,villa,house)", type=openapi.TYPE_STRING, example="villa,house"),
            openapi.Parameter('cities', openapi.IN_QUERY, description="Comma-separated city names", type=openapi.TYPE_STRING, example="damascus,tartous"),
            openapi.Parameter('min_price', openapi.IN_QUERY, description="Minimum price in USD", type=openapi.TYPE_NUMBER, example=100000),
            openapi.Parameter('max_price', openapi.IN_QUERY, description="Maximum price in USD", type=openapi.TYPE_NUMBER, example=500000),
            openapi.Parameter('min_area', openapi.IN_QUERY, description="Minimum area in square meters", type=openapi.TYPE_NUMBER, example=100),
            openapi.Parameter('max_area', openapi.IN_QUERY, description="Maximum area in square meters", type=openapi.TYPE_NUMBER, example=200),
            openapi.Parameter('min_rooms', openapi.IN_QUERY, description="Minimum number of rooms", type=openapi.TYPE_INTEGER, example=2),
            openapi.Parameter('max_rooms', openapi.IN_QUERY, description="Maximum number of rooms", type=openapi.TYPE_INTEGER, example=4),
            openapi.Parameter('min_bathrooms', openapi.IN_QUERY, description="Minimum number of bathrooms", type=openapi.TYPE_INTEGER, example=2),
            openapi.Parameter('max_bathrooms', openapi.IN_QUERY, description="Maximum number of bathrooms", type=openapi.TYPE_INTEGER, example=4),
            openapi.Parameter('is_for_rent', openapi.IN_QUERY, description="Filter by rental status", type=openapi.TYPE_BOOLEAN, example=False),
            openapi.Parameter('search', openapi.IN_QUERY, description="Search in city or location text", type=openapi.TYPE_STRING, example="beach view"),
            openapi.Parameter('ordering', openapi.IN_QUERY, description="Order by fields (comma-separated). Prefix with '-' for descending", type=openapi.TYPE_STRING, example="-price,area"),
        ],
        responses={
            200: openapi.Response(description="List of properties matching criteria", schema=PropertySerializer(many=True)),
            401: "Unauthorized" # This is needed for the 'mine=true' case
        },
        security=[{'Bearer': []}] # The Bearer token is now optional for the general list
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
    
    
class PropertyDetailView(APIView):
    permission_classes = [AllowAny]

    @swagger_auto_schema(
        operation_id="get_property_details",
        operation_description="Retrieve full details of a specific property.",
        responses={
            200: openapi.Response(description="Property details retrieved successfully.", schema=PropertyDetailSerializer),
            404: "Not found. The property does not exist."
        }
    )
    def get(self, request, property_id):
        try:
            property_instance = Property.objects.select_related('owner').prefetch_related('images', 'facilities').get(id=property_id)
        except Property.DoesNotExist:
            return Response({"detail": "Property not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = PropertyDetailSerializer(property_instance, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    
# class AddPropertyView(APIView):
#     permission_classes = [IsAuthenticated, IsSeller]

#     @swagger_auto_schema(
#         operation_id="add_property",
#         operation_description="""
#         Add a new property.
#         Only users in seller mode can perform this action.
#         Property must be unique (combination of type, city, area, and price).
#         """,
#         # FIX: Explicitly define the request_body schema including property_registry_number
#         request_body=openapi.Schema(
#             type=openapi.TYPE_OBJECT,
#             required=[
#                 'ptype', 'city', 'number_of_rooms', 'area', 'price',
#                 'is_for_rent', 'latitude', 'longitude'
#             ],
#             properties={
#                 'ptype': openapi.Schema(type=openapi.TYPE_STRING, enum=[choice[0] for choice in Property.PROPERTY_TYPES]),
#                 'city': openapi.Schema(type=openapi.TYPE_STRING),
#                 'number_of_rooms': openapi.Schema(type=openapi.TYPE_INTEGER),
#                 'bathrooms': openapi.Schema(type=openapi.TYPE_INTEGER), # Removed required=False
#                 'area': openapi.Schema(type=openapi.TYPE_NUMBER),
#                 'location_text': openapi.Schema(type=openapi.TYPE_STRING, required=False),
#                 'price': openapi.Schema(type=openapi.TYPE_NUMBER),
#                 'is_for_rent': openapi.Schema(type=openapi.TYPE_BOOLEAN),
#                 'details': openapi.Schema(type=openapi.TYPE_STRING, required=False),
#                 'latitude': openapi.Schema(type=openapi.TYPE_NUMBER),
#                 'longitude': openapi.Schema(type=openapi.TYPE_NUMBER),
#                 # NEW: Add property_registry_number for input
#                 'property_registry_number': openapi.Schema(
#                     type=openapi.TYPE_STRING,
#                     description="Official registration number of the property (optional for input).",
#                     required=False,
#                     nullable=True,
#                     max_length=50
#                 ),
#             },
#             # You can also use example for the whole schema if you want
#         ),
#         responses={
#             201: openapi.Response("Property created", PropertySerializer),
#             400: openapi.Response("Bad request", examples={
#                 "application/json": {
#                     "non_field_errors": ["You already have a similar property listed."]
#                 }
#             }),
#             403: "Forbidden. You must be in seller mode."
#         }
#     )
#     def post(self, request):
#         serializer = PropertySerializer(
#             data=request.data,
#             context={'request': request}
#         )
        
#         if serializer.is_valid():
#             serializer.save(owner=request.user)
#             return Response(serializer.data, status=status.HTTP_201_CREATED)
            
#         return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
# class EditPropertyView(APIView):
#     permission_classes = [IsAuthenticated, IsSeller]

#     @swagger_auto_schema(
#         operation_id="edit_property",
#         operation_description="Partially update an existing property. Only the owner of the property (in seller mode) can edit it.",
#         # FIX: Explicitly define the request_body schema including property_registry_number
#         request_body=openapi.Schema(
#             type=openapi.TYPE_OBJECT,
#             properties={
#                 'ptype': openapi.Schema(type=openapi.TYPE_STRING, enum=[choice[0] for choice in Property.PROPERTY_TYPES], required=False),
#                 'city': openapi.Schema(type=openapi.TYPE_STRING, required=False),
#                 'number_of_rooms': openapi.Schema(type=openapi.TYPE_INTEGER, required=False),
#                 'bathrooms': openapi.Schema(type=openapi.TYPE_INTEGER, required=False),
#                 'area': openapi.Schema(type=openapi.TYPE_NUMBER, required=False),
#                 'location_text': openapi.Schema(type=openapi.TYPE_STRING, required=False),
#                 'price': openapi.Schema(type=openapi.TYPE_NUMBER, required=False),
#                 'is_for_rent': openapi.Schema(type=openapi.TYPE_BOOLEAN, required=False),
#                 'details': openapi.Schema(type=openapi.TYPE_STRING, required=False),
#                 'latitude': openapi.Schema(type=openapi.TYPE_NUMBER, required=False),
#                 'longitude': openapi.Schema(type=openapi.TYPE_NUMBER, required=False),
#                 'active': openapi.Schema(type=openapi.TYPE_BOOLEAN, required=False), # Allow changing active status
#                 # NEW: Add property_registry_number for input
#                 'property_registry_number': openapi.Schema(
#                     type=openapi.TYPE_STRING,
#                     description="Official registration number of the property (optional for input).",
#                     required=False,
#                     nullable=True,
#                     max_length=50
#                 ),
#             },
#             # No 'required' array at top level for PATCH, as all fields are optional
#         ),
#         responses={
#             200: openapi.Response(description="Property updated successfully.", schema=PropertySerializer),
#             400: "Bad request. Invalid data provided.",
#             403: "Forbidden. You must be the owner of the property and in seller mode to edit it.",
#             404: "Not found. The property does not exist."
#         }
#     )
#     def patch(self, request, property_id):
#         try:
#             property_instance = Property.objects.get(id=property_id, owner=request.user)
#         except Property.DoesNotExist:
#             return Response({"detail": "Property not found."}, status=status.HTTP_404_NOT_FOUND)

#         serializer = PropertySerializer(property_instance, data=request.data, partial=True, context={'request': request})
#         if serializer.is_valid():
#             serializer.save()
#             return Response(serializer.data, status=status.HTTP_200_OK)
#         return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
 
class AddPropertyView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]

    @swagger_auto_schema(
        operation_id="add_property",
        operation_description="""
        Add a new property.
        Only users in seller mode can perform this action.
        Property must be unique (combination of type, city, area, and price).
        """,
        # FIX: Explicitly define the request_body schema including property_registry_number
        request_body=openapi.Schema(
            type=TYPE_OBJECT, # Use imported TYPE_OBJECT
            required=[
                'ptype', 'city', 'number_of_rooms', 'area', 'price',
                'is_for_rent', 'latitude', 'longitude'
            ],
            properties={
                'ptype': Schema(type=TYPE_STRING, enum=[choice[0] for choice in Property.PROPERTY_TYPES]), # Use imported Schema, TYPE_STRING
                'city': Schema(type=TYPE_STRING), # Use imported Schema, TYPE_STRING
                'number_of_rooms': Schema(type=TYPE_INTEGER), # Use imported Schema, TYPE_INTEGER
                'bathrooms': Schema(type=TYPE_INTEGER), # Use imported Schema, TYPE_INTEGER
                'area': Schema(type=TYPE_NUMBER), # Use imported TYPE_NUMBER
                'location_text': Schema(type=TYPE_STRING, nullable=True), # Use imported Schema, TYPE_STRING, nullable=True
                'price': Schema(type=TYPE_NUMBER), # Use imported TYPE_NUMBER
                'is_for_rent': Schema(type=TYPE_BOOLEAN), # Use imported TYPE_BOOLEAN
                'details': Schema(type=TYPE_STRING, nullable=True), # Use imported Schema, TYPE_STRING, nullable=True
                'latitude': Schema(type=TYPE_NUMBER), # Use imported TYPE_NUMBER
                'longitude': Schema(type=TYPE_NUMBER), # Use imported TYPE_NUMBER
                # NEW: Add property_registry_number for input
                'property_registry_number': Schema(
                    type=TYPE_STRING, # Use imported TYPE_STRING
                    description="Official registration number of the property (optional for input).",
                    nullable=True, # Use nullable=True instead of required=False for optional fields in properties
                    max_length=50
                ),
            },
            # You can also use example for the whole schema if you want
        ),
        responses={
            201: openapi.Response("Property created", PropertySerializer),
            400: openapi.Response("Bad request", examples={
                "application/json": {
                    "non_field_errors": ["You already have a similar property listed."]
                }
            }),
            403: "Forbidden. You must be in seller mode."
        }
    )
    def post(self, request):
        serializer = PropertySerializer(
            data=request.data,
            context={'request': request}
        )
        
        if serializer.is_valid():
            serializer.save(owner=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class EditPropertyView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]

    @swagger_auto_schema(
        operation_id="edit_property",
        operation_description="Partially update an existing property. Only the owner of the property (in seller mode) can edit it.",
        # FIX: Explicitly define the request_body schema including property_registry_number
        request_body=openapi.Schema(
            type=TYPE_OBJECT, # Use imported TYPE_OBJECT
            properties={
                'ptype': Schema(type=TYPE_STRING, enum=[choice[0] for choice in Property.PROPERTY_TYPES], nullable=True), # Use imported Schema, TYPE_STRING, nullable=True
                'city': Schema(type=TYPE_STRING, nullable=True), # Use imported Schema, TYPE_STRING, nullable=True
                'number_of_rooms': Schema(type=TYPE_INTEGER, nullable=True), # Use imported Schema, TYPE_INTEGER, nullable=True
                'bathrooms': Schema(type=TYPE_INTEGER, nullable=True), # Use imported Schema, TYPE_INTEGER, nullable=True
                'area': Schema(type=TYPE_NUMBER, nullable=True), # Use imported TYPE_NUMBER, nullable=True
                'location_text': Schema(type=TYPE_STRING, nullable=True), # Use imported Schema, TYPE_STRING, nullable=True
                'price': Schema(type=TYPE_NUMBER, nullable=True), # Use imported TYPE_NUMBER, nullable=True
                'is_for_rent': Schema(type=TYPE_BOOLEAN, nullable=True), # Use imported TYPE_BOOLEAN, nullable=True
                'details': Schema(type=TYPE_STRING, nullable=True), # Use imported Schema, TYPE_STRING, nullable=True
                'latitude': Schema(type=TYPE_NUMBER, nullable=True), # Use imported TYPE_NUMBER, nullable=True
                'longitude': Schema(type=TYPE_NUMBER, nullable=True), # Use imported TYPE_NUMBER, nullable=True
                'active': Schema(type=TYPE_BOOLEAN, nullable=True), # Use imported TYPE_BOOLEAN, nullable=True
                # NEW: Add property_registry_number for input
                'property_registry_number': Schema(
                    type=TYPE_STRING, # Use imported TYPE_STRING
                    description="Official registration number of the property (optional for input).",
                    nullable=True, # Use nullable=True instead of required=False
                    max_length=50
                ),
            },
            # No 'required' array at top level for PATCH, as all fields are optional
        ),
        responses={
            200: openapi.Response(description="Property updated successfully.", schema=PropertySerializer),
            400: "Bad request. Invalid data provided.",
            403: "Forbidden. You must be the owner of the property and in seller mode to edit it.",
            404: "Not found. The property does not exist."
        }
    )
    def patch(self, request, property_id):
        try:
            property_instance = Property.objects.get(id=property_id, owner=request.user)
        except Property.DoesNotExist:
            return Response({"detail": "Property not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = PropertySerializer(property_instance, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
#############FACILITY###########

class AddFacilityView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]

    @swagger_auto_schema(
        operation_id="add_facility_to_property",
        operation_description="Add a facility to a property.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['facility_id'],
            properties={
                'facility_id': openapi.Schema(type=openapi.TYPE_INTEGER, description="The ID of the facility to add."),
            },
        ),
        responses={
            201: openapi.Response(description="Facility added successfully.", schema=FacilitySerializer),
            400: "Bad request. Invalid data provided.",
            403: "Forbidden. You must be the owner of the property and in seller mode to add a facility.",
            404: "Not found. The property or facility does not exist."
        }
    )
    def post(self, request, property_id):
        try:
            property_instance = Property.objects.get(id=property_id, owner=request.user)
        except Property.DoesNotExist:
            return Response({"detail": "Property not found."}, status=status.HTTP_404_NOT_FOUND)

        # Validate the input using a serializer
        serializer = AddFacilitySerializer(data=request.data, context={'property': property_instance})
        if serializer.is_valid():
            facility_id = serializer.validated_data['facility_id']
            try:
                facility_instance = Facility.objects.get(id=facility_id)
            except Facility.DoesNotExist:
                return Response({"detail": "Facility not found."}, status=status.HTTP_404_NOT_FOUND)

            # Check for duplicates
            if PropertyFacility.objects.filter(property=property_instance, facility=facility_instance).exists():
                return Response({"detail": "Facility is already associated with the property."}, status=status.HTTP_400_BAD_REQUEST)

            # Create the intermediate model instance explicitly
            PropertyFacility.objects.create(property=property_instance, facility=facility_instance)

            # Return the serialized facility data
            return Response(FacilitySerializer(facility_instance).data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class RemoveFacilityView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]

    @swagger_auto_schema(
        operation_id="remove_facility_from_property",
        operation_description="Remove a facility from a property.",
        responses={
            204: "No content. Facility removed successfully.",
            403: "Forbidden. You must be the owner of the property and in seller mode to remove a facility.",
            404: "Not found. The property or facility does not exist."
        }
    )
    def delete(self, request, property_id, facility_id):
        try:
            property_instance = Property.objects.get(id=property_id, owner=request.user)
            facility_instance = Facility.objects.get(id=facility_id)
        except Property.DoesNotExist:
            return Response({"detail": "Property not found."}, status=status.HTTP_404_NOT_FOUND)
        except Facility.DoesNotExist:
            return Response({"detail": "Facility not found."}, status=status.HTTP_404_NOT_FOUND)

        property_instance.facilities.remove(facility_instance)
        return Response(status=status.HTTP_204_NO_CONTENT)
    

    

#######################IMAGE#############

class AddPropertyImageView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]
    parser_classes = [MultiPartParser]  # Required for file uploads

    @swagger_auto_schema(
        operation_id="add_property_image",
        operation_description="Upload a new image for a property.",
        manual_parameters=[
            openapi.Parameter(
                'property_id',
                openapi.IN_PATH,
                description="The ID of the property to which the image will be added.",
                type=openapi.TYPE_INTEGER,
                required=True
            ),
            openapi.Parameter(
                'image',
                openapi.IN_FORM,
                description="The image file to upload.",
                type=openapi.TYPE_FILE,
                required=True
            ),
            openapi.Parameter(
                'caption',
                openapi.IN_FORM,
                description="Optional caption for the image.",
                type=openapi.TYPE_STRING,
                required=False
            ),
        ],
        responses={
            201: openapi.Response(description="Image uploaded successfully.", schema=PropertyImageSerializer),
            400: "Bad request. Invalid data provided.",
            403: "Forbidden. You must be the owner of the property and in seller mode to add an image.",
            404: "Not found. The property does not exist."
        }
    )
    def post(self, request, property_id):
        try:
            property_instance = Property.objects.get(id=property_id, owner=request.user)
        except Property.DoesNotExist:
            return Response({"detail": "Property not found."}, status=status.HTTP_404_NOT_FOUND)

        # Validate the input using a serializer
        serializer = PropertyImageSerializer(
            data=request.data,
            context={'property_id': property_id, 'request': request}  # Pass the request to the serializer
        )
        if serializer.is_valid():
            # Create the PropertyImage instance explicitly
            image_file = serializer.validated_data.get('image')
            if not image_file:
                return Response({"detail": "Image file is required."}, status=status.HTTP_400_BAD_REQUEST)

            # Save the PropertyImage instance
            property_image_instance = PropertyImage.objects.create(
                property=property_instance,
                image=image_file,
                caption=serializer.validated_data.get('caption', None)  # Optional field
            )

            # Serialize the saved instance to include the image_url field
            response_serializer = PropertyImageSerializer(
                property_image_instance,
                context={'request': request}  # Ensure the request is passed for image_url generation
            )
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
class DeletePropertyImageView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]

    @swagger_auto_schema(
        operation_id="delete_property_image",
        operation_description="Delete an image from a property.",
        manual_parameters=[
            openapi.Parameter(
                'property_id',
                openapi.IN_PATH,
                description="The ID of the property from which the image will be deleted.",
                type=openapi.TYPE_INTEGER,
                required=True
            ),
            openapi.Parameter(
                'image_id',
                openapi.IN_PATH,
                description="The ID of the image to delete.",
                type=openapi.TYPE_INTEGER,
                required=True
            )
        ],
        responses={
            204: openapi.Response(
                description="No content. Image deleted successfully."
            ),
            403: openapi.Response(
                description="Forbidden. You must be the owner of the property and in seller mode to delete an image.",
                examples={
                    "application/json": {
                        "detail": "You do not have permission to delete this image."
                    }
                }
            ),
            404: openapi.Response(
                description="Not found. The property or image does not exist.",
                examples={
                    "application/json": {
                        "detail": "Property not found."
                    },
                    "application/json": {
                        "detail": "Image not found."
                    }
                }
            )
        }
    )
    def delete(self, request, property_id, image_id):
        try:
            # Ensure the property exists and belongs to the authenticated user
            property_instance = Property.objects.get(id=property_id, owner=request.user)
        except Property.DoesNotExist:
            return Response({"detail": "Property not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            # Ensure the image exists and belongs to the specified property
            image_instance = PropertyImage.objects.get(id=image_id, property=property_instance)
        except PropertyImage.DoesNotExist:
            return Response({"detail": "Image not found."}, status=status.HTTP_404_NOT_FOUND)

        # Delete the image
        image_path = image_instance.image.path
        
        image_instance.delete()
        try:
            if os.path.exists(image_path):
                os.remove(image_path)
                
        except FileNotFoundError:
            pass 
        if os.path.exists(image_path):
            os.remove(image_path)
        return Response(status=status.HTTP_204_NO_CONTENT)
    
class EditImageCaptionView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]
    parser_classes = [MultiPartParser]

    @swagger_auto_schema(
        operation_id="edit_image_caption",
        operation_description="Update the caption of an image.",
        manual_parameters=[
            openapi.Parameter(
                'property_id',
                openapi.IN_PATH,
                description="The ID of the property to which the image belongs.",
                type=openapi.TYPE_INTEGER,
                required=True
            ),
            openapi.Parameter(
                'image_id',
                openapi.IN_PATH,
                description="The ID of the image whose caption will be updated.",
                type=openapi.TYPE_INTEGER,
                required=True
            ),
            openapi.Parameter(
                'caption',
                openapi.IN_FORM,
                description="The new caption for the image.",
                type=openapi.TYPE_STRING,
                required=False
            ),
        ],
        responses={
            200: openapi.Response(
                description="Caption updated successfully.",
                schema=PropertyImageSerializer
            ),
            400: "Bad request. Invalid data provided.",
            403: "Forbidden. You must be the owner of the property and in seller mode to edit the caption.",
            404: "Not found. The property or image does not exist."
        }
    )
    def patch(self, request, property_id, image_id):
        try:
            # Ensure the property exists and belongs to the authenticated user
            property_instance = Property.objects.get(id=property_id, owner=request.user)
        except Property.DoesNotExist:
            return Response({"detail": "Property not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            # Ensure the image exists and belongs to the specified property
            image_instance = PropertyImage.objects.get(id=image_id, property=property_instance)
        except PropertyImage.DoesNotExist:
            return Response({"detail": "Image not found."}, status=status.HTTP_404_NOT_FOUND)

        # Validate and update the caption
        serializer = PropertyImageSerializer(
            image_instance,
            data=request.data,
            partial=True,
            context={'request': request, 'property_id': property_id}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
class DeleteImageCaptionView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]

    @swagger_auto_schema(
        operation_id="delete_image_caption",
        operation_description="Remove the caption of an image.",
        manual_parameters=[
            openapi.Parameter(
                'property_id',
                openapi.IN_PATH,
                description="The ID of the property to which the image belongs.",
                type=openapi.TYPE_INTEGER,
                required=True
            ),
            openapi.Parameter(
                'image_id',
                openapi.IN_PATH,
                description="The ID of the image whose caption will be removed.",
                type=openapi.TYPE_INTEGER,
                required=True
            )
        ],
        responses={
            200: openapi.Response(
                description="Caption deleted successfully.",
                schema=PropertyImageSerializer
            ),
            403: "Forbidden. You must be the owner of the property and in seller mode to delete the caption.",
            404: "Not found. The property or image does not exist."
        }
    )
    def delete(self, request, property_id, image_id):
        try:
            # Ensure the property exists and belongs to the authenticated user
            property_instance = Property.objects.get(id=property_id, owner=request.user)
        except Property.DoesNotExist:
            return Response({"detail": "Property not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            # Ensure the image exists and belongs to the specified property
            image_instance = PropertyImage.objects.get(id=image_id, property=property_instance)
        except PropertyImage.DoesNotExist:
            return Response({"detail": "Image not found."}, status=status.HTTP_404_NOT_FOUND)

        # Remove the caption
        image_instance.caption = None
        image_instance.save()

        # Serialize the updated instance
        serializer = PropertyImageSerializer(image_instance, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    
###########FAVOURITE PROPERTIES########
class AddToFavoritesView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_id="add_to_favorites",
        operation_description="Add a property to the authenticated user's favorites.",
        manual_parameters=[
            openapi.Parameter(
                'property_id',
                openapi.IN_PATH,
                description="The ID of the property to add to favorites.",
                type=openapi.TYPE_INTEGER,
                required=True
            )
        ],
        responses={
            200: openapi.Response(
                description="Property added to favorites successfully.",
                examples={
                    "application/json": {
                        "detail": "Property added to favorites."
                    }
                }
            ),
            400: openapi.Response(
                description="Bad request. Invalid property ID or already favorited.",
                examples={
                    "application/json": {
                        "detail": "Invalid property ID."
                    },
                    "application/json": {
                        "detail": "Property is already in favorites."
                    }
                }
            ),
            404: openapi.Response(
                description="Property not found.",
                examples={
                    "application/json": {
                        "detail": "Property not found."
                    }
                }
            )
        }
    )
    def post(self, request, property_id):
        try:
            # Retrieve the property by ID
            property = Property.objects.get(id=property_id)
        except Property.DoesNotExist:
            return Response({"detail": "Property not found."}, status=status.HTTP_404_NOT_FOUND)

        user = request.user

        # Check if the property is already favorited
        if user.favorite_properties.filter(id=property.id).exists():
            return Response({"detail": "Property is already in favorites."}, status=status.HTTP_400_BAD_REQUEST)

        # Add the property to the user's favorites
        #user.favorite_properties.add(property)
        FavoriteProperty.objects.create(user=user, property=property)
        return Response({"detail": "Property added to favorites."}, status=status.HTTP_200_OK)
    
class RemoveFromFavoritesView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_id="remove_from_favorites",
        operation_description="Remove a property from the authenticated user's favorites.",
        manual_parameters=[
            openapi.Parameter(
                'property_id',
                openapi.IN_PATH,
                description="The ID of the property to remove from favorites.",
                type=openapi.TYPE_INTEGER,
                required=True
            )
        ],
        responses={
            200: openapi.Response(
                description="Property removed from favorites successfully.",
                examples={
                    "application/json": {
                        "detail": "Property removed from favorites."
                    }
                }
            ),
            400: openapi.Response(
                description="Bad request. Invalid property ID or not favorited.",
                examples={
                    "application/json": {
                        "detail": "Property is not in favorites."
                    }
                }
            ),
            404: openapi.Response(
                description="Property not found.",
                examples={
                    "application/json": {
                        "detail": "Property not found."
                    }
                }
            )
        }
    )
    def delete(self, request, property_id):
        try:
            # Retrieve the property by ID
            property = Property.objects.get(id=property_id)
        except Property.DoesNotExist:
            return Response({"detail": "Property not found."}, status=status.HTTP_404_NOT_FOUND)

        user = request.user

        # Check if the property is in the user's favorites
        if not user.favorite_properties.filter(id=property.id).exists():
            return Response({"detail": "Property is not in favorites."}, status=status.HTTP_400_BAD_REQUEST)

        # Remove the property from the user's favorites
        user.favorite_properties.remove(property)
        return Response({"detail": "Property removed from favorites."}, status=status.HTTP_200_OK)
    
class ListFavoritePropertiesView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PropertySerializer

    @swagger_auto_schema(
        operation_id="list_favorite_properties",
        operation_description="List all properties favorited by the authenticated user.",
        responses={
            200: openapi.Response(
                description="List of favorite properties retrieved successfully.",
                schema=PropertySerializer(many=True),
                examples={
                    "application/json": [
                        {
                            "id": 1,
                            "city": "New York",
                            "ptype": "Flat",
                            "price": "1500.00"
                        },
                        {
                            "id": 2,
                            "city": "Los Angeles",
                            "ptype": "Villa",
                            "price": "3000.00"
                        }
                    ]
                }
            ),
            401: openapi.Response(
                description="Authentication required.",
                examples={
                    "application/json": {
                        "detail": "Authentication credentials were not provided."
                    }
                }
            )
        }
    )
    def get_queryset(self):
        # Retrieve the authenticated user's favorite properties
        return self.request.user.favorite_properties.all().prefetch_related('images')
    
#######RATING###########
class RatePropertyView(APIView): # <--- NEW CLASS
    """
    API endpoint to allow authenticated users to rate a property.
    A user cannot rate their own property or rate the same property multiple times.
    Updates the property's average rating and notifies the owner.
    """
    permission_classes = [IsAuthenticated] # Only authenticated users can rate

    @swagger_auto_schema(
        operation_id="rate_property",
        operation_description="Submit a rating for a specific property. Users cannot rate their own properties or rate the same property multiple times. This updates the property's average rating and notifies the owner.",
        manual_parameters=[
            openapi.Parameter(
                'property_id',
                openapi.IN_PATH,
                description="The ID of the property to rate.",
                type=openapi.TYPE_INTEGER,
                required=True
            ),
        ],
        request_body=RatingSerializer, # <--- Use the RatingSerializer for input (it has value and comment)
        responses={
            201: openapi.Response(description="Rating submitted successfully.", schema=RatingSerializer), # Returns the created Rating object
            400: "Bad request (e.g., invalid value).",
            403: "Forbidden (e.g., rating own property, already rated).", # Updated error message
            404: "Property not found."
        },
        security=[{'Bearer': []}]
    )
    def post(self, request, property_id):
        try:
            property_instance = Property.objects.get(id=property_id)
        except Property.DoesNotExist:
            return Response({"detail": "Property not found."}, status=status.HTTP_404_NOT_FOUND)

        user = request.user

        # --- Validation: User cannot rate their own property ---
        if property_instance.owner == user:
            return Response({"detail": "You cannot rate your own property."}, status=status.HTTP_403_FORBIDDEN)

        # --- Use RatingSerializer for input and validation ---
        # Pass user and property_instance to serializer context for validation
        serializer = RatingSerializer(data=request.data, context={'request': request, 'property_instance': property_instance, 'user': user})
        serializer.is_valid(raise_exception=True)

        # Create the new Rating object
        # The serializer's validate method already checked 'rate once' and 'not owner'
        rating_instance = serializer.save(user=user, property=property_instance) # Save the new Rating object

        # --- Trigger Signal for Property.rating update and Notification ---
        # The post_save signal on the Rating model will handle:
        # 1. Recalculating Property.rating (average)
        # 2. Creating the Notification
        # 3. Dispatching the Celery task
        print(f"DEBUG: Rating {rating_instance.pk} created for Property {property_instance.pk} by User {user.id}. Signal will handle updates and notification.")

        # Return the newly created Rating object
        return Response(RatingSerializer(rating_instance).data, status=status.HTTP_201_CREATED)