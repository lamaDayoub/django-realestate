from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.core.exceptions import ObjectDoesNotExist

class CustomTokenSerializer(TokenObtainPairSerializer):
    """Adds custom user data to JWT tokens, including profile information."""
    
    def validate(self, attrs):
        # Get the default token response
        data = super().validate(attrs)
        
        try:
            # Retrieve the user's profile
            profile = self.user.profile
            first_name = profile.first_name or ''
            last_name = profile.last_name or ''
        except ObjectDoesNotExist:
            # If the profile does not exist, use empty strings as defaults
            first_name = ''
            last_name = ''

        # Add user information to the token response
        data.update({
            'user_id': self.user.id,
            'email': self.user.email,
            'first_name': first_name,
            'last_name': last_name,
        })
        return data