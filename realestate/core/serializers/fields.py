from rest_framework import serializers
from django.utils import timezone

class DamascusDateTimeField(serializers.DateTimeField):
    def to_representation(self, value):
        value = timezone.localtime(value)
        return super().to_representation(value)