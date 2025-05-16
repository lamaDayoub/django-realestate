from django.urls import path
from .views import SignUpView,logout_view,ResetPasswordView,CustomLoginView,PublicProfileView,ProfileView,ChangePasswordView,ForgotPasswordView,VerifyCodeView
from .views import ToggleSellerModeView,CheckActivationStatusView
urlpatterns = [
    path('signup/',SignUpView.as_view(),name='signup'),
    path('login/',CustomLoginView.as_view(),name='login'),
    path('logout/', logout_view, name='logout'),
    path('profile/', ProfileView.as_view(), name='profile'),
    path('forgot-password/', ForgotPasswordView.as_view(), name='forgot-password'),
    path('verify-code/', VerifyCodeView.as_view(), name='verify-code'),
    path('change-password/',ChangePasswordView.as_view(),name='change-password'),
    path('set-new-password/',ResetPasswordView.as_view(),name='set-new-password'),
    path('see-profile/<int:user_id>/',PublicProfileView.as_view(),name='see-others-profile'),
    #path('delete-photo/', ProfileView.as_view({'delete': 'delete_photo'}), name='delete_profile_photo'),
    path('profile/is-seller/', ToggleSellerModeView.as_view(), name='toggle_seller_mode'),
    path('check-activation-status/', CheckActivationStatusView.as_view(), name='check_activation_status'),
    
]