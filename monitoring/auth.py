# monitoring/auth.py

from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView, LogoutView
from django.views.generic import CreateView, UpdateView, ListView
from django.urls import reverse_lazy
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from .models import UserProfile


class CustomAuthenticationForm(AuthenticationForm):
    """Custom login form with Bootstrap styling"""
    username = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Логін'}),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Пароль'}),
    )

    error_messages = {
        'invalid_login': "Будь ласка, введіть правильний логін та пароль. Зверніть увагу, що поля можуть бути чутливі до регістру.",
        'inactive': "Цей обліковий запис неактивний.",
    }


class CustomLoginView(LoginView):
    """Custom login view with our template"""
    form_class = CustomAuthenticationForm
    template_name = 'auth/login.html'
    redirect_authenticated_user = True


class CustomLogoutView(LogoutView):
    """Custom logout view"""
    next_page = 'login'


class CustomUserCreationForm(UserCreationForm):
    """User registration form with Bootstrap styling"""
    first_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Ім'я"})
    )
    last_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Прізвище'})
    )
    email = forms.EmailField(
        max_length=254,
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email'})
    )
    username = forms.CharField(
        max_length=30,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Логін'})
    )
    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Пароль'})
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Підтвердження пароля'})
    )

    error_messages = {
        'password_mismatch': "Паролі не співпадають.",
        'password_too_short': "Пароль занадто короткий. Має містити щонайменше 8 символів.",
        'password_too_common': "Цей пароль занадто поширений.",
        'password_entirely_numeric': "Пароль не може містити тільки цифри.",
    }

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'password1', 'password2')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']

        if commit:
            user.save()
            # Create a UserProfile with default 'regular' role
            UserProfile.objects.create(user=user, role='regular')

        return user


class RegisterView(CreateView):
    """User registration view"""
    form_class = CustomUserCreationForm
    template_name = 'auth/register.html'
    success_url = reverse_lazy('login')

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('dashboard')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Реєстрація успішна! Тепер ви можете увійти.")
        return response


class UserProfileForm(forms.ModelForm):
    """Form for updating user profile roles - only for admins"""

    class Meta:
        model = UserProfile
        fields = ['role']
        widgets = {
            'role': forms.Select(attrs={'class': 'form-select'}),
        }


class UserManagementView(UserPassesTestMixin, ListView):
    """List all users except the current one - only for admins"""
    model = User
    template_name = 'auth/user_management.html'
    context_object_name = 'users'

    def test_func(self):
        try:
            return self.request.user.is_authenticated and self.request.user.profile.is_admin
        except UserProfile.DoesNotExist:
            return False

    def get_queryset(self):
        # Exclude the current user from the queryset
        return User.objects.exclude(id=self.request.user.id).prefetch_related('profile')


class UserProfileEditView(UserPassesTestMixin, UpdateView):
    """Edit a user's profile - only for admins"""
    model = UserProfile
    form_class = UserProfileForm
    template_name = 'auth/edit_user_profile.html'
    success_url = reverse_lazy('user_management')

    def test_func(self):
        try:
            return self.request.user.is_authenticated and self.request.user.profile.is_admin
        except UserProfile.DoesNotExist:
            return False

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_being_edited'] = self.object.user
        return context

    def form_valid(self, form):
        messages.success(self.request, f"Профіль користувача {self.object.user.username} оновлено.")
        return super().form_valid(form)