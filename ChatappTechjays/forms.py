from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
import re   

class SignupForm(forms.Form):
    full_name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(
            attrs={'placeholder': 'Full Name', 'class': 'input-field'}
        )
    )
    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={'placeholder': 'Email', 'class': 'input-field'}
        )
    )
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={'placeholder': 'Password', 'class': 'input-field'}
        )
    )

    def clean_full_name(self):
        full_name = self.cleaned_data.get('full_name')
        if not re.match(r'^[A-Za-z ]+$', full_name):
            raise ValidationError("Name must contain only alphabet letters and spaces. Numbers are not allowed!")
        return full_name

    # ✅ Email Validation (Check Duplicate)
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(username=email).exists():  # Username = email
            raise ValidationError("This email is already registered!")
        return email

    # ✅ Password Validation (8–15 chars + 1 special symbol)
    def clean_password(self):
        password = self.cleaned_data.get('password')
        if len(password) < 8 or len(password) > 15:
            raise ValidationError("Password must be between 8 and 15 characters long!")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            raise ValidationError("Password must contain at least one special character [!@#$%^&*(),.?\":{}|<>]")
        return password

class SignInForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={'placeholder': 'Email', 'class': 'input-field'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={'placeholder': 'Password', 'class': 'input-field'})
    )
