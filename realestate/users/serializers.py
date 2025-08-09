from rest_framework import serializers
from .models import  Profile
from djoser.serializers import UserCreateSerializer as BaseUserCreateSerializer
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from .utils import validate_user_email
User = get_user_model()

class UserCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id','email', 'password']
        extra_kwargs = {
            'password': {'write_only': True},
        }

    def validate_email(self, value):
        # Validate the email using the custom function
        if not validate_user_email(value):
            raise serializers.ValidationError("Invalid email address or not a Gmail address.")
        
        # Check if the email is already registered
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        
        return value

    def create(self, validated_data):
        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            is_active=False  # Ensure the user is inactive initially
        )
        return user

class PublicProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ['id','first_name', 'last_name', 'photo', 'country', 'birth_date', 'is_identity_verified']
        read_only_fields = ['id','first_name', 'last_name', 'photo', 'country', 'birth_date', 'is_identity_verified'] 
        
class ProfileSerializer(serializers.ModelSerializer):
    points = serializers.SerializerMethodField()
    is_seller = serializers.SerializerMethodField()
    national_id_number = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=20)
    is_identity_verified = serializers.BooleanField(read_only=True)

    class Meta:
        model = Profile
        fields = ['id','first_name', 'last_name', 'gender','photo', 'birth_date', 'country', 'phone_number', 'national_id_number', 'is_identity_verified', 'points', 'is_seller']
        read_only_fields = ['id', 'points', 'is_identity_verified']
    def get_points(self, obj):
        """
        Retrieve the user's points from the related User model.
        """
        return obj.user.points

    def get_is_seller(self, obj):
        """
        Retrieve the user's seller status from the related User model.
        """
        return obj.user.is_seller

    def update(self, instance, validated_data):
        """
        Update the profile fields, allowing null values to clear fields.
        """
        instance.first_name = validated_data.get('first_name', instance.first_name)
        instance.last_name = validated_data.get('last_name', instance.last_name)
        instance.photo = validated_data.get('photo', instance.photo)
        instance.gender=validated_data.get('gender', instance.gender)
        instance.birth_date=validated_data.get('birth_date', instance.birth_date)
        instance.country=validated_data.get('country', instance.country)
        instance.phone_number=validated_data.get('phone_number', instance.phone_number)
        if 'national_id_number' in validated_data:
            instance.national_id_number = validated_data['national_id_number']

        # Handle clearing fields with null values
        if 'last_name' in validated_data and validated_data['last_name'] is None:
            instance.last_name = None
        if 'photo' in validated_data and validated_data['photo'] == '':
            instance.photo = None
        if 'country' in validated_data and validated_data['country'] is None:
            instance.country = None
        if 'phone_number' in validated_data and validated_data['phone_number'] == '':
            instance.phone_number = None
        if 'first_name' in validated_data and validated_data['first_name'] == '':
            instance.first_name = None
        if 'gender' in validated_data and validated_data['gender'] == '':
            instance.gender = None
        if 'birth_date' in validated_data and validated_data['birth_date'] == '':
            instance.birth_date = None

        instance.save()
        return instance

    def has_changed(self):
        """
        Check if any fields were updated.
        """
        # Compare validated_data with instance's current values
        # Exclude read-only fields that are not part of input
        updatable_fields = [
            'first_name', 'last_name', 'gender', 'photo', 'birth_date',
            'country', 'phone_number', 'national_id_number'
        ]
        
        for field in updatable_fields:
            if field in self.validated_data:
                # Special handling for ImageField if it's being cleared
                if field == 'photo' and self.validated_data[field] == '':
                    if self.instance.photo: # If there was an existing photo
                        return True
                    continue # No photo to clear, no change
                
                if getattr(self.instance, field) != self.validated_data[field]:
                    return True
        return False
        
class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True)

    def validate_current_password(self, value):
        if not self.context['request'].user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect")
        return value

    def validate_new_password(self, value):
        user = self.context['request'].user
        validate_password(value, user)
        
        # Check against current password
        if user.check_password(value):
            raise serializers.ValidationError("New password cannot be the same as current password")
            
        # Check against last 6 passwords
        
        last_passwords = user.password_histories.order_by('-created_at')[:6]
        for old_record in last_passwords:
            if check_password(value, old_record.hashed_password):
                raise serializers.ValidationError("You cannot reuse any of your last 6 passwords")
                
        return value
    


class ActivationStatusSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    
class ChargePointsSerializer(serializers.Serializer):
    """
    Serializer for the dummy API to charge user points.
    """
    bank_name = serializers.CharField(
        max_length=100,
        help_text="Dummy bank name (e.g., 'Albarakeh bank', 'Pemo bank', 'PayPal')."
    )
    credit_card_number = serializers.CharField(
        max_length=16, # Standard credit card length, though dummy
        help_text="Dummy credit card number (e.g., '1111222233334444')."
    )
    password = serializers.CharField(
        max_length=100, # Dummy password for simulation
        help_text="Dummy password for the credit card (e.g., '1234')."
    )
    amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0.01,
        help_text="Amount of money to charge (e.g., in SYP or USD)."
    )

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be positive.")
        return value

    def validate(self, data):
        # Dummy validation for demonstration purposes
        if data['bank_name'] not in ['Albarakeh bank', 'Pemo bank', 'PayPal']:
            raise serializers.ValidationError({"bank_name": "Invalid bank name. Use 'Albarakeh bank', 'Pemo bank', 'PayPal'."})
        if not data['credit_card_number'].isdigit() or len(data['credit_card_number']) != 16:
            raise serializers.ValidationError({"credit_card_number": "Dummy credit card number must be 16 digits."})
        if data['password'] != "1234": # Simple dummy password check
            raise serializers.ValidationError({"password": "Dummy password incorrect."})
        
        return data
