from rest_framework.generics import ListAPIView
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from .models import Property,PropertyImage,Facility,PropertyFacility, FavoriteProperty
from .serializers import PropertySerializer,PropertyDetailSerializer,PropertyImageSerializer,FacilitySerializer,AddFacilitySerializer
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
from django.conf import settings
class PropertyListView(ListAPIView):
    queryset = Property.objects.all()
    serializer_class = PropertySerializer
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend, CaseInsensitiveSearchFilter, OrderingFilter]
    filterset_fields = ['city', 'ptype', 'is_for_rent']  # Fields to filter by
    search_fields = ['city', 'location_text']  # Fields to search by
    ordering_fields = ['price', 'area']  # Fields to order by
    pagination_class = PageNumberPagination  # Default pagination

    @swagger_auto_schema(
        operation_id="list_properties",
        operation_description="List all properties with optional filtering, searching, and pagination.",
        manual_parameters=[
            openapi.Parameter('city', openapi.IN_QUERY, description="Filter properties by city.", type=openapi.TYPE_STRING),
            openapi.Parameter('ptype', openapi.IN_QUERY, description="Filter properties by type.", type=openapi.TYPE_STRING),
            openapi.Parameter('is_for_rent', openapi.IN_QUERY, description="Filter properties by rental status.", type=openapi.TYPE_BOOLEAN),
            openapi.Parameter('search', openapi.IN_QUERY, description="Search properties by city or location text.", type=openapi.TYPE_STRING),
            openapi.Parameter('ordering', openapi.IN_QUERY, description="Order results by price or area.", type=openapi.TYPE_STRING),
        ],
        responses={
            200: openapi.Response(description="Properties retrieved successfully.", schema=PropertySerializer(many=True)),
        }
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
            property_instance = Property.objects.get(id=property_id)
        except Property.DoesNotExist:
            return Response({"detail": "Property not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = PropertyDetailSerializer(property_instance, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    
class AddPropertyView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]

    @swagger_auto_schema(
        operation_id="add_property",
        operation_description="Add a new property. Only users in seller mode can perform this action.",
        request_body=PropertySerializer,
        responses={
            201: openapi.Response(description="Property created successfully.", schema=PropertySerializer),
            400: "Bad request. Invalid data provided.",
            403: "Forbidden. You must be in seller mode to add a property."
        }
    )
    def post(self, request):
        serializer = PropertySerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save(owner=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class EditPropertyView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]

    @swagger_auto_schema(
        operation_id="edit_property",
        operation_description="Partially update an existing property. Only the owner of the property (in seller mode) can edit it.",
        request_body=PropertySerializer,
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

        serializer = PropertySerializer(property_instance, data=request.data, partial=True)
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
        user.favorite_properties.add(property)
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
        return self.request.user.favorite_properties.all()