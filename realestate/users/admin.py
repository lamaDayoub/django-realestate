from django.contrib import admin
from .models import User,Profile,VerificationCode,PasswordHistory
# Register your models here.
admin.site.register(User)
admin.site.register(Profile)
admin.site.register(VerificationCode)
admin.site.register(PasswordHistory)