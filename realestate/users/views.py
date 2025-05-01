from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from djoser.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.permissions import AllowAny
from drf_yasg.utils import swagger_auto_schema
from django.contrib.auth.hashers import check_password
from .utils import send_verification_email,send_password_change_notification
from drf_yasg import openapi
from rest_framework_simplejwt.views import TokenObtainPairView
from .authentication.serializers import CustomTokenSerializer
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from .serializers import UserCreateSerializer,ProfileSerializer,ChangePasswordSerializer
from .models import User,Profile,PasswordHistory,VerificationCode
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.parsers import MultiPartParser
from .serializers import ProfileSerializer,PublicProfileSerializer
from rest_framework.generics import GenericAPIView
from rest_framework_simplejwt.tokens import OutstandingToken, BlacklistedToken
User = get_user_model()




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
        purpose = request.data.get('purpose')  # 'activation' or 'password_reset'

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            verification = VerificationCode.objects.filter(user=user, purpose=purpose).latest('created_at')
        except VerificationCode.DoesNotExist:
            return Response({"detail": "No verification code found."}, status=status.HTTP_404_NOT_FOUND)

        # Check expiry
        if verification.is_expired():
            return Response({"detail": "Code expired. Please request a new code."}, status=status.HTTP_400_BAD_REQUEST)

        # Check if blocked
        if verification.is_blocked():
            return Response({"detail": "Too many wrong attempts. Please request a new code."}, status=status.HTTP_400_BAD_REQUEST)

        # Check code
        if verification.code != code:
            verification.increase_attempts()
            tries_left = verification.max_attempts - verification.attempts
            return Response({"detail": f"Invalid code. {tries_left} tries left."}, status=status.HTTP_400_BAD_REQUEST)

        # Correct code!
        if purpose == 'activation':
            user.is_active = True
            user.save()
        elif purpose == 'password_reset':
            return Response({"detail": "Code verified. Now you can reset your password."})

        verification.delete()  # Clean up used code

        return Response({"detail": "Verification successful."}, status=status.HTTP_200_OK)

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
            user = User.objects.get(pk=user_id)
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
        profile, created = Profile.objects.get_or_create(user=self.request.user)
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



class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]
    
    @swagger_auto_schema(
        operation_id="forgot_password",
        operation_description="Initiates the password reset process by sending a verification code to the user's email. The user needs to provide their email address.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['email'],
            properties={
                'email': openapi.Schema(type=openapi.TYPE_STRING, description="The email address of the user requesting a password reset."),
            },
        ),
        responses={
            200: openapi.Response(
                description="Verification code sent to email.",
                examples={
                    'application/json': {
                        'detail': 'Verification code sent to your email.',
                    }
                }
            ),
            400: openapi.Response(
                description="Bad request, e.g., email is missing.",
                examples={
                    'application/json': {
                        'detail': 'Email is required.',
                    }
                }
            ),
            404: openapi.Response(
                description="User with the provided email not found.",
                examples={
                    'application/json': {
                        'detail': 'User with this email does not exist.',
                    }
                }
            ),
        }
    )

    def post(self, request):
        email = request.data.get('email')
        
        # Check if the email is provided
        if not email:
            return Response({"detail": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        # Check if the user exists
        try:
            user = get_user_model().objects.get(email=email)
        except get_user_model().DoesNotExist:
            return Response({"detail": "User with this email does not exist."}, status=status.HTTP_404_NOT_FOUND)

        # Send verification email (code)
        send_verification_email(user, purpose='password_reset')

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
            return Response({"detail": "Email, code, and new password are required."}, status=status.HTTP_400_BAD_REQUEST)

        # Check if the user exists
        try:
            user = get_user_model().objects.get(email=email)
        except get_user_model().DoesNotExist:
            return Response({"detail": "User with this email does not exist."}, status=status.HTTP_404_NOT_FOUND)

        # Find the verification code for this user and purpose
        try:
            verification_code = VerificationCode.objects.get(user=user, code=code, purpose='password_reset')
        except VerificationCode.DoesNotExist:
            return Response({"detail": "Invalid verification code."}, status=status.HTTP_400_BAD_REQUEST)

        # Check if the code has expired
        if verification_code.is_expired():
            return Response({"detail": "Verification code has expired."}, status=status.HTTP_400_BAD_REQUEST)

        # Check if the code has been blocked due to too many attempts
        if verification_code.is_blocked():
            return Response({"detail": "Too many incorrect attempts. Please try again later."}, status=status.HTTP_400_BAD_REQUEST)
        # Ensure the new password is not the same as the current password
        if check_password(new_password, user.password):
            return Response({"detail": "New password cannot be the same as the current password."}, status=status.HTTP_400_BAD_REQUEST)

        # Before updating the password, save the current hashed password to the password history
        if user.password:
            PasswordHistory.objects.create(user=user, hashed_password=user.password)

        # Update the user's password and save it
        user.set_password(new_password)
        user.save()

        # Delete the used verification code after successful password reset
        verification_code.delete()

        # Check if the password history exceeds 6 records, delete the oldest
        if user.password_histories.count() > 6:
            user.password_histories.order_by('created_at').last().delete()
        tokens = OutstandingToken.objects.filter(user=user)
        for token in tokens:
            BlacklistedToken.objects.get_or_create(token=token)
        send_password_change_notification(user)

        return Response({"detail": "Password reset successful. You have been logged out of all devices."}, status=status.HTTP_200_OK)

        
