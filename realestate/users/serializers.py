from rest_framework import serializers
from .models import User, Profile
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
        fields = ['id','first_name', 'last_name', 'photo', 'country', 'birth_date']
        read_only_fields = ['id','first_name', 'last_name', 'photo', 'country', 'birth_date' ] 
        
class ProfileSerializer(serializers.ModelSerializer):
    points = serializers.SerializerMethodField()
    is_seller = serializers.SerializerMethodField()
    class Meta:
        model = Profile
        fields = ['id','first_name', 'last_name', 'gender','photo', 'birth_date', 'country', 'phone_number', 'points', 'is_seller']
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
        return any(
            getattr(self.instance, field) != self.validated_data.get(field)
            for field in self.Meta.fields
            if field in self.validated_data
        )
        
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