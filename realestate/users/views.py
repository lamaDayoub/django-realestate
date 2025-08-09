from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from djoser.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.permissions import AllowAny
from django.core.files.storage import default_storage
from drf_yasg.utils import swagger_auto_schema
from django.contrib.auth.hashers import check_password
from .utils import send_verification_email,send_password_change_notification,verify_code
from django.db import transaction
from drf_yasg import openapi
from rest_framework_simplejwt.views import TokenObtainPairView
from .authentication.serializers import CustomTokenSerializer
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from .serializers import UserCreateSerializer,ProfileSerializer,ChangePasswordSerializer,ActivationStatusSerializer
from .models import Profile,PasswordHistory,VerificationCode
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.parsers import MultiPartParser
from .serializers import ProfileSerializer,PublicProfileSerializer,ChargePointsSerializer
from rest_framework.generics import GenericAPIView
from rest_framework_simplejwt.tokens import OutstandingToken, BlacklistedToken
from django.db.models import F 
User = get_user_model()


class CheckActivationStatusView(APIView):
    permission_classes = []  # Allow any user to check activation status

    @swagger_auto_schema(
        operation_id="check_activation_status",
        operation_description="Check if a user is activated based on their email.",
        request_body=ActivationStatusSerializer,
        responses={
            200: openapi.Response(
                description="Activation status retrieved successfully.",
                examples={
                    "application/json": {
                        "exists": True,
                        "is_activated": True
                    }
                }
            ),
            400: openapi.Response(
                description="Bad request. Missing or invalid fields.",
                examples={
                    "application/json": {
                        "email": ["This field is required."]
                    }
                }
            )
        }
    )
    def post(self, request):
        # Validate the input using the serializer
        serializer = ActivationStatusSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data['email']

        # Check if the user exists
        try:
            user = User.objects.get(email=email)
            exists = True
            is_activated = user.is_active  # Check if the user is activated
        except User.DoesNotExist:
            exists = False
            is_activated = False

        # Return the response
        return Response(
            {"exists": exists, "is_activated": is_activated},
            status=status.HTTP_200_OK
        )

class SignUpView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [AllowAny]

    @swagger_auto_schema(
        operation_id="user_signup",
        operation_description="Register a new user. The user will receive an activation email.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['email', 'password'],
            properties={
                'email': openapi.Schema(type=openapi.TYPE_STRING, description='User email address'),
                'password': openapi.Schema(type=openapi.TYPE_STRING, description='Password for the new user'),
            },
        ),
        responses={
            201: openapi.Response(
                description="User successfully created, activation email sent.",
                examples={
                    'application/json': {
                        'detail': 'Check your email for the activation code.'
                    }
                }
            ),
            400: openapi.Response(
                description="Invalid input or missing required fields.",
                examples={
                    'application/json': {
                        'email': ['This field is required.'],
                        'password': ['This field is required.']
                    }
                }
            ),
        }
    )
    def post(self, request):
        serializer = UserCreateSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save(is_active=False)
            return Response({"detail": "Check your email for the activation code."}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        



class VerifyCodeView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [JWTAuthentication]
    @swagger_auto_schema(
        operation_id="verify_code",
        operation_description="Verify a code sent for account activation or password reset.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['email', 'code', 'purpose'],
            properties={
                'email': openapi.Schema(type=openapi.TYPE_STRING, description='User email address'),
                'code': openapi.Schema(type=openapi.TYPE_STRING, description='Verification code sent to the user'),
                'purpose': openapi.Schema(type=openapi.TYPE_STRING, description='Purpose of the code. It can either be "activation" or "password_reset"'),
            },
        ),
        responses={
            200: openapi.Response(
                description="Verification successful, the user is either activated or can now reset their password.",
                examples={
                    'application/json': {
                        'detail': 'Verification successful.'
                    }
                }
            ),
            400: openapi.Response(
                description="Invalid code, code expired, or blocked due to too many attempts.",
                examples={
                    'application/json': {
                        'detail': 'Invalid code. 3 tries left.',
                    }
                }
            ),
            404: openapi.Response(
                description="User not found or no verification code available for the user.",
                examples={
                    'application/json': {
                        'detail': 'User not found.',
                    }
                }
            ),
        }
    )

    def post(self, request):
        email = request.data.get('email')
        code = request.data.get('code')
        purpose = request.data.get('purpose')

        # Use the utility function
        result = verify_code(email, code, purpose)
        
        # If result is a Response (error), return it
        if isinstance(result, Response):
            return result
        
        # Otherwise, proceed with success logic
        user, verification = result

        if purpose == 'activation':
            user.is_active = True
            user.save()
        elif purpose == 'password_reset':
            return Response(
                {"detail": "Code verified. Now you can reset your password."},
                status=status.HTTP_200_OK
            )

        verification.delete()  # Clean up
        return Response(
            {"detail": "Verification successful."}, 
            status=status.HTTP_200_OK
        )

class CustomLoginView(TokenObtainPairView):
    authentication_classes=[JWTAuthentication]
    serializer_class = CustomTokenSerializer
    @swagger_auto_schema(
        operation_id="user_login",
        operation_description="Authenticate user and obtain JWT tokens",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['email', 'password'],
            properties={
                'email': openapi.Schema(type=openapi.TYPE_STRING, description='User email'),
                'password': openapi.Schema(type=openapi.TYPE_STRING, description='User password'),
            },
        ),
        responses={
            200: openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'access': openapi.Schema(type=openapi.TYPE_STRING, description='Access token'),
                    'refresh': openapi.Schema(type=openapi.TYPE_STRING, description='Refresh token'),
                },
            ),
            401: "Unauthorized. Invalid credentials."
        }
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)
 
@swagger_auto_schema(
    method='post',
    operation_id="logout_all_devices",
    operation_description="Log out the authenticated user from all devices by blacklisting all their active tokens.",
    responses={
        200: openapi.Response(
            description="Successfully logged out from all devices.",
            examples={
                "application/json": {
                    "detail": "Successfully logged out from all devices."
                }
            }
        ),
        401: openapi.Response(
            description="Unauthorized. Authentication credentials were not provided or invalid.",
            examples={
                "application/json": {
                    "detail": "Authentication credentials were not provided."
                }
            }
        )
    }
)  
@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def logout_view(request):
    user = request.user

    # Blacklist all outstanding tokens for the user
    tokens = OutstandingToken.objects.filter(user=user)
    for token in tokens:
        BlacklistedToken.objects.get_or_create(token=token)

    return Response({"detail": "Successfully logged out from all devices."}, status=status.HTTP_200_OK)
    
######################profile########################

class PublicProfileView(APIView):
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser]
    
    @swagger_auto_schema(
    operation_id="get_public_profile",
    operation_description="Retrieve a user's public profile by user ID.",
    manual_parameters=[
        openapi.Parameter(
            'user_id',  # Match the parameter name in the URL and view
            openapi.IN_PATH,
            description="The ID of the user whose public profile is being retrieved.",
            type=openapi.TYPE_INTEGER,
            required=True
        )
    ],
    responses={
        200: openapi.Response(
            description="Public profile retrieved successfully.",
            schema=PublicProfileSerializer,
            examples={
                "application/json": {
                    "first_name": "John",
                    "last_name": "Doe",
                    "birth_date":"18/4/2004",
                    "country":"syria",
                    "photo": "http://example.com/media/userphotos/user_1/photo.jpg"
                }
            }
        ),
        404: openapi.Response(
            description="User or profile not found.",
            examples={
                "application/json": {
                    "detail": "User or profile not found."
                }
            }
        )
    }
)
    
    def get(self, request, user_id):
        """
        Retrieve a user's public profile by user ID.
        """
        try:
            user = User.objects.select_related('profile').get(pk=user_id)
            profile = user.profile
        except (User.DoesNotExist, Profile.DoesNotExist):
            return Response(
                {"detail": "User or profile not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = PublicProfileSerializer(profile)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ProfileView(RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]
    serializer_class = ProfileSerializer
    @swagger_auto_schema(
        operation_id="retrieve_or_update_profile",
        operation_description="Retrieve or update the authenticated user's profile.",
        responses={
            200: openapi.Response(
                description="User profile retrieved or updated successfully.",
                schema=ProfileSerializer,
            ),
            401: openapi.Response(
                description="Authentication required.",
                examples={
                    'application/json': {
                        'detail': 'Authentication credentials were not provided.',
                    }
                }
            ),
        }
    )
    def get_object(self):
        """
        Retrieve or create the user's profile.
        """
        profile, created = Profile.objects.select_related('user').get_or_create(user=self.request.user)
        return profile

    @swagger_auto_schema(
        operation_id="retrieve_profile",
        operation_description="Retrieve the authenticated user's profile, including an 'is_empty' flag indicating whether the profile has any information.and his points and seller mode.",
        responses={
            200: openapi.Response(
                description="Profile retrieved successfully.",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        "profile": openapi.Schema(
                            type=openapi.TYPE_OBJECT,
                            properties={
                                "first_name": openapi.Schema(
                                    type=openapi.TYPE_STRING,
                                    description="The user's first name."
                                ),
                                "last_name": openapi.Schema(
                                    type=openapi.TYPE_STRING,
                                    description="The user's last name."
                                ),
                                "gender": openapi.Schema(
                                    type=openapi.TYPE_STRING,
                                    enum=['M', 'F', 'O'],
                                    description="The user's gender (M: Male, F: Female, O: Other)."
                                ),
                                "birth_date": openapi.Schema(
                                    type=openapi.FORMAT_DATE,
                                    description="The user's birth date."
                                ),
                                "country": openapi.Schema(
                                    type=openapi.TYPE_STRING,
                                    description="The user's country."
                                ),
                                "phone_number": openapi.Schema(
                                    type=openapi.TYPE_STRING,
                                    description="The user's phone number."
                                ),
                                "photo": openapi.Schema(
                                    type=openapi.TYPE_STRING,
                                    description="URL of the user's profile photo (if uploaded)."
                                ),
                                "national_id_number": openapi.Schema(
                                    type=openapi.TYPE_STRING,
                                    description="National identity number for verification purposes. Can be updated by user."
                                ),
                            },
                        ),
                        "is_empty": openapi.Schema(
                            type=openapi.TYPE_BOOLEAN,
                            description="Indicates whether the profile is empty (all fields are null)."
                        ),
                    },
                ),
                examples={
                    "application/json": {
                        "profile": {
                            "first_name": "John",
                            "last_name": "Doe",
                            "gender": "M",
                            "birth_date": "1990-01-01",
                            "country": "USA",
                            "phone_number": "+1234567890",
                            "photo": "http://example.com/media/userphotos/user_1/photo.jpg"
                        },
                        "is_empty": False
                    }
                }
            ),
            401: "Unauthorized. Authentication required."
        }
    )
    def retrieve(self, request, *args, **kwargs):
        """
        Add an 'is_empty' flag to the response if the profile has no information.
        """
        instance = self.get_object()
        serializer = self.get_serializer(instance)

        # Check if the profile is empty
        is_empty = not (instance.first_name and instance.last_name and instance.photo and 
                        instance.gender and instance.country and instance.birth_date and instance.phone_number)

        response_data = {
            "profile": serializer.data,
            "is_empty": is_empty,
        }
        return Response(response_data)

    @swagger_auto_schema(
        operation_id="partial_update_profile",
        operation_description="Partially update the authenticated user's profile. Only fields included in the request will be updated.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "first_name": openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description="The user's first name."
                ),
                "last_name": openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description="The user's last name."
                ),
                "gender": openapi.Schema(
                    type=openapi.TYPE_STRING,
                    enum=['M', 'F', 'O'],
                    description="The user's gender (M: Male, F: Female, O: Other)."
                ),
                "birth_date": openapi.Schema(
                    type=openapi.FORMAT_DATE,
                    description="The user's birth date."
                ),
                "country": openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description="The user's country."
                ),
                "phone_number": openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description="The user's phone number."
                ),
                "photo": openapi.Schema(
                    type=openapi.TYPE_FILE,
                    description="The user's profile photo."
                ),
            },
        ),
        responses={
            200: openapi.Response(
                description="Profile updated successfully.",
                schema=ProfileSerializer,
                examples={
                    "application/json": {
                        "first_name": "Johnny",
                        "last_name": "Doe",
                        "gender": "M",
                        "birth_date": "1990-01-01",
                        "country": "USA",
                        "phone_number": "+1234567890",
                        "photo": "http://example.com/media/userphotos/user_1/photo.jpg"
                    }
                }
            ),
            200: openapi.Response(
                description="No changes were made.",
                examples={
                    "application/json": {
                        "detail": "No changes were made."
                    }
                }
            ),
            400: "Bad request. Missing or invalid fields.",
            401: "Unauthorized. Authentication required."
        }
    )
    def partial_update(self, request, *args, **kwargs):
        """
        Partially update the user's profile.
        """
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)

        if serializer.is_valid():
            # Check if any fields were actually updated
            new_photo = request.data.get('photo')
            if new_photo and instance.photo:
            # Construct the full path to the old photo
                old_photo_path = instance.photo.name  # This already includes the custom directory path
            # Delete the old photo file from storage
                if default_storage.exists(old_photo_path):
                    default_storage.delete(old_photo_path)
            if not serializer.has_changed():
                return Response(
                    {"detail": "No changes were made."},
                    status=status.HTTP_200_OK
                )

            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        """
        Disallow full updates (PUT).
        """
        return Response(
            {"detail": "Method PUT is not allowed. Use PATCH for partial updates."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )
        
    @swagger_auto_schema(
    operation_id="delete_profile_photo",
    operation_description="Delete the authenticated user's profile photo.",
    responses={
        204: openapi.Response(
            description="Profile photo deleted successfully.",
        ),
        401: "Unauthorized. Authentication required.",
        404: "Not Found. The user does not have a profile photo.",
    }
    )
    def delete_photo(self, request, *args, **kwargs):
        """
        Delete the authenticated user's profile photo.
        """
        instance = self.get_object()
        if not instance.photo:
            return Response(
                {"detail": "No profile photo to delete."},
                status=status.HTTP_404_NOT_FOUND
            )
        # Delete the photo file from storage
        instance.photo.delete(save=False)
        # Set the photo field to null
        instance.photo = None
        instance.save()
        return Response(status=status.HTTP_204_NO_CONTENT)       
    def delete(self, request, *args, **kwargs):
        """
        Route DELETE requests to the delete_photo method.
        """
        return self.delete_photo(request, *args, **kwargs)
        
##############3password#############



class ChangePasswordView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordSerializer
    authentication_classes = [JWTAuthentication] 
    @swagger_auto_schema(
        operation_id="change_password",
        operation_description="Change the password for the authenticated user. The current password must be provided and validated, and the new password will be checked to ensure it hasn't been reused in the last 6 passwords.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['current_password', 'new_password'],
            properties={
                'current_password': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description="The current password of the user."
                ),
                'new_password': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description="The new password for the user."
                ),
            },
        ),
        responses={
            200: openapi.Response(
                description="Password changed successfully. The user is logged out of all devices.",
                examples={
                    "application/json": {
                        "message": "Password updated successfully. You have been logged out of all devices."
                    }
                }
            ),
            400: openapi.Response(
                description="Bad request, e.g., current password incorrect or reused password.",
                examples={
                    "application/json": {
                        "detail": "Current password is incorrect."
                    },
                    "application/json": {
                        "detail": "You cannot reuse your last 6 passwords."
                    }
                }
            ),
            401: openapi.Response(
                description="Unauthorized. Authentication credentials were not provided.",
                examples={
                    "application/json": {
                        "detail": "Authentication credentials were not provided."
                    }
                }
            )
        }
    )


    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        new_password = serializer.validated_data['new_password']

        # Store current password in history before changing it
        PasswordHistory.objects.create(
            user=user,
            hashed_password=user.password  # Already hashed
        )

        # Set new password
        user.set_password(new_password)
        user.save()

        # Keep only the last 6 passwords
        histories = user.password_histories.order_by('-created_at')
        if histories.count() > 6:
            for history in histories[6:]:
                history.delete()

        # Blacklist all outstanding tokens for the user
        tokens = OutstandingToken.objects.filter(user=user)
        for token in tokens:
            BlacklistedToken.objects.get_or_create(token=token)
        send_password_change_notification(user)

        return Response({"message": "Password updated successfully. You have been logged out of all devices."}, status=status.HTTP_200_OK)
      

class SendVerificationCodeView(APIView):
    permission_classes = [AllowAny]

    @swagger_auto_schema(
        operation_id="send_verification_code",
        operation_description="Send a verification code to the user's email for account activation or password reset.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['email', 'purpose'],
            properties={
                'email': openapi.Schema(type=openapi.TYPE_STRING, description="The email address of the user."),
                'purpose': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    enum=['activation', 'password_reset'],
                    description="The purpose of the verification code (activation or password reset)."
                ),
            },
        ),
        responses={
            200: openapi.Response(
                description="Verification code sent successfully.",
                examples={
                    "application/json": {
                        "detail": "Verification code sent to your email."
                    }
                }
            ),
            400: openapi.Response(
                description="Bad request, e.g., too many requests or invalid input.",
                examples={
                    "application/json": {
                        "detail": "Too many requests. Please try again later."
                    }
                }
            ),
            404: openapi.Response(
                description="User not found.",
                examples={
                    "application/json": {
                        "detail": "User with this email does not exist."
                    }
                }
            ),
        }
    )
    def post(self, request):
        email = request.data.get('email')
        purpose = request.data.get('purpose')

        # Validate inputs
        if not email or not purpose:
            return Response({"detail": "Email and purpose are required."}, status=status.HTTP_400_BAD_REQUEST)

        # Check if the user exists
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"detail": "User with this email does not exist."}, status=status.HTTP_404_NOT_FOUND)

        # Ensure the purpose is valid
        if purpose not in ['activation', 'password_reset']:
            return Response({"detail": "Invalid purpose."}, status=status.HTTP_400_BAD_REQUEST)

        # Send verification email and handle rate limiting
        try:
            send_verification_email(user, purpose)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"detail": "Verification code sent to your email."}, status=status.HTTP_200_OK)




class ResetPasswordView(APIView):
    permission_classes = [AllowAny]
   
    @swagger_auto_schema(
        operation_id="reset_password",
        operation_description="Reset a user's password using a verification code sent to their email.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['email', 'code', 'new_password'],
            properties={
                'email': openapi.Schema(type=openapi.TYPE_STRING, description='The email address of the user.'),
                'code': openapi.Schema(type=openapi.TYPE_STRING, description='The verification code sent to the user.'),
                'new_password': openapi.Schema(type=openapi.TYPE_STRING, description='The new password for the user.'),
            },
        ),
        responses={
            200: openapi.Response(
                description="Password reset successful. The user is logged out of all devices.",
                examples={
                    "application/json": {
                        "detail": "Password reset successful. You have been logged out of all devices."
                    }
                }
            ),
            400: openapi.Response(
                description="Bad request. Missing or invalid fields, expired code, or too many attempts.",
                examples={
                    "application/json": {
                        "detail": "Email, code, and new password are required."
                    },
                    "application/json": {
                        "detail": "Invalid verification code."
                    },
                    "application/json": {
                        "detail": "Verification code has expired."
                    },
                    "application/json": {
                        "detail": "Too many incorrect attempts. Please try again later."
                    }
                }
            ),
            404: openapi.Response(
                description="User not found.",
                examples={
                    "application/json": {
                        "detail": "User with this email does not exist."
                    }
                }
            )
        }
    )
    def post(self, request):
        email = request.data.get('email')
        code = request.data.get('code')
        new_password = request.data.get('new_password')

        # Check if required fields are provided
        if not email or not code or not new_password:
            return Response({"detail": "Email, code, and new password are required."}, 
                       status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():  # The only new line added
                result = verify_code(email, code, 'password_reset')
                if isinstance(result, Response):
                    return result  # Return error if any
            
                user, verification = result
                # Ensure the new password is not the same as the current password
                if check_password(new_password, user.password):
                    return Response({"detail": "New password cannot be the same as the current password."}, 
                              status=status.HTTP_400_BAD_REQUEST)

                # Before updating the password, save the current hashed password to the password history
                if user.password:
                    PasswordHistory.objects.create(user=user, hashed_password=user.password)

                # Update the user's password and save it
                user.set_password(new_password)
                user.save()

                # Delete the used verification code after successful password reset
                verification.delete()

                # Check if the password history exceeds 6 records, delete the oldest
                if user.password_histories.count() > 6:
                    user.password_histories.order_by('created_at').last().delete()
            
                tokens = OutstandingToken.objects.filter(user=user)
                for token in tokens:
                    BlacklistedToken.objects.get_or_create(token=token)
            
                send_password_change_notification(user)

                return Response({"detail": "Password reset successful. You have been logged out of all devices."}, 
                          status=status.HTTP_200_OK)

        except Exception:
            return Response({"detail": "An error occurred during password reset. Please try again."},
                      status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    
##############photot +isseller mode#####





class ToggleSellerModeView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_id="toggle_seller_mode",
        operation_description="Toggle the 'is_seller' attribute for the authenticated user.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['is_seller'],
            properties={
                'is_seller': openapi.Schema(
                    type=openapi.TYPE_BOOLEAN,
                    description="Set to true to enable seller mode, false to disable."
                ),
            },
        ),
        responses={
            200: openapi.Response(
                description="Seller mode toggled successfully.",
                examples={
                    "application/json": {
                        "is_seller": True
                    }
                }
            ),
            400: openapi.Response(
                description="Bad request. Missing or invalid fields.",
                examples={
                    "application/json": {
                        "detail": "is_seller field is required."
                    }
                }
            ),
            401: openapi.Response(
                description="Unauthorized. Authentication credentials were not provided.",
                examples={
                    "application/json": {
                        "detail": "Authentication credentials were not provided."
                    }
                }
            ),
        }
    )
    def patch(self, request):
        """
        Toggle the 'is_seller' attribute for the authenticated user.
        """
        # Extract the 'is_seller' value from the request body
        is_seller = request.data.get('is_seller')
    
        # Validate that 'is_seller' is provided
        if is_seller is None:
            return Response(
                {"detail": "is_seller field is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        #  Get the authenticated user
        user = request.user

        # Update the 'is_seller' attribute
        try:
            user.is_seller = is_seller
            user.save()
        except Exception as e:
            return Response(
                {"detail": "Failed to update is_seller status."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Return the updated 'is_seller' status
        return Response(
            {"is_seller": user.is_seller},
            status=status.HTTP_200_OK
        )
        
        
class ChargePointsView(APIView):
    """
    API endpoint to simulate charging a user's account with points.
    This is a dummy API for demonstration purposes and does not integrate with real payment gateways.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ChargePointsSerializer

    @swagger_auto_schema(
        operation_id="charge_points",
        operation_description="""
        Simulate charging the authenticated user's account with points.
        This API is for demonstration purposes only.
        """,
        request_body=ChargePointsSerializer,
        responses={
            200: openapi.Response(
                description="Points charged successfully.",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'detail': openapi.Schema(type=openapi.TYPE_STRING, description="Success message."),
                        'new_points_balance': openapi.Schema(type=openapi.TYPE_INTEGER, description="The user's new points balance.")
                    }
                ),
                examples={
                    "application/json": {
                        "detail": "Points charged successfully.",
                        "new_points_balance": 600
                    }
                }
            ),
            400: openapi.Response(
                description="Bad request. Invalid input or dummy validation failed.",
                examples={
                    "application/json": {
                        "bank_name": ["Invalid bank name. Use 'Albarakeh bank', 'Pemo bank', or 'PayPal'."]
                    }
                }
            ),
            401: "Unauthorized. Authentication required."
        },
        security=[{'Bearer': []}]
    )
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        amount_to_charge = serializer.validated_data['amount']
        user = request.user

        # Simulate adding points (atomic update for safety, though dummy)
        with transaction.atomic():
            user.points = F('points') + (amount_to_charge*100)
            user.save(update_fields=['points'])
            user.refresh_from_db() # Get the updated points value from the database

        return Response(
            {
                "detail": "Points charged successfully.",
                "new_points_balance": user.points
            },
            status=status.HTTP_200_OK
        )
