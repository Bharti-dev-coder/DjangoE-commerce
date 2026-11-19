import re

from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from core.models import Address, Order


class RegistrationForm(forms.Form):
    """Storefront registration while keeping the existing email-as-username design."""

    name = forms.CharField(
        max_length=150,
        label='Full name',
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'id': 'name',
                'placeholder': 'Enter your full name',
                'autocomplete': 'name',
            }
        ),
    )
    email = forms.EmailField(
        max_length=254,
        label='Email address',
        widget=forms.EmailInput(
            attrs={
                'class': 'form-control',
                'id': 'email',
                'placeholder': 'Enter your email',
                'autocomplete': 'email',
            }
        ),
    )
    phone = forms.CharField(
        max_length=20,
        label='Phone number',
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'id': 'phone',
                'placeholder': 'Enter your phone number',
                'autocomplete': 'tel',
            }
        ),
    )
    password = forms.CharField(
        label='Password',
        help_text='Use at least 8 characters and avoid common passwords.',
        widget=forms.PasswordInput(
            attrs={
                'class': 'form-control',
                'id': 'password',
                'placeholder': 'Create a password',
                'autocomplete': 'new-password',
            }
        ),
    )
    confirm_password = forms.CharField(
        label='Confirm password',
        widget=forms.PasswordInput(
            attrs={
                'class': 'form-control',
                'id': 'confirmPassword',
                'placeholder': 'Confirm your password',
                'autocomplete': 'new-password',
            }
        ),
    )
    gender = forms.ChoiceField(
        required=False,
        choices=(
            ('', 'Prefer not to say'),
            ('male', 'Male'),
            ('female', 'Female'),
            ('other', 'Other'),
        ),
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'gender'}),
    )
    country = forms.ChoiceField(
        required=False,
        choices=(
            ('', 'Select country'),
            ('india', 'India'),
            ('usa', 'USA'),
            ('uk', 'UK'),
            ('canada', 'Canada'),
        ),
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'country'}),
    )
    terms = forms.BooleanField(
        required=False,
        label='I agree to the terms and conditions',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'terms'}),
    )

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(username__iexact=email).exists() or User.objects.filter(
            email__iexact=email
        ).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email

    def clean_password(self):
        password = self.cleaned_data['password']
        try:
            validate_password(password)
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages) from exc
        return password

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        if password and confirm_password and password != confirm_password:
            self.add_error('confirm_password', 'Passwords do not match.')
        return cleaned_data

    def save(self):
        data = self.cleaned_data
        return User.objects.create_user(
            username=data['email'],
            email=data['email'],
            first_name=data['name'],
            password=data['password'],
        )


class CheckoutForm(forms.Form):
    """Customer, delivery-address, and payment details for checkout."""

    full_name = forms.CharField(
        max_length=150,
        label='Full name',
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'autocomplete': 'name',
                'placeholder': 'Full name',
            }
        ),
    )
    email = forms.EmailField(
        max_length=254,
        label='Email address',
        widget=forms.EmailInput(
            attrs={
                'class': 'form-control',
                'autocomplete': 'email',
                'placeholder': 'you@example.com',
            }
        ),
    )
    phone = forms.CharField(
        max_length=20,
        label='Mobile number',
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'autocomplete': 'tel',
                'placeholder': '10-digit mobile number',
            }
        ),
    )

    saved_address = forms.ModelChoiceField(
        queryset=Address.objects.none(),
        required=False,
        label='Saved delivery address',
        empty_label='Use a new delivery address',
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'savedAddress'}),
    )
    delivery_full_name = forms.CharField(
        max_length=150,
        required=False,
        label='Delivery full name',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Recipient full name'}),
    )
    delivery_phone = forms.CharField(
        max_length=20,
        required=False,
        label='Delivery phone number',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Recipient phone number'}),
    )
    house_number = forms.CharField(
        max_length=120,
        required=False,
        label='House / flat number',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'House or flat number'}),
    )
    street = forms.CharField(
        max_length=200,
        required=False,
        label='Street / locality',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Street or locality'}),
    )
    landmark = forms.CharField(
        max_length=200,
        required=False,
        label='Landmark (optional)',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nearby landmark'}),
    )
    city = forms.CharField(
        max_length=100,
        required=False,
        label='City',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'City'}),
    )
    state = forms.CharField(
        max_length=100,
        required=False,
        label='State',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'State'}),
    )
    pin_code = forms.CharField(
        max_length=12,
        required=False,
        label='PIN code',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'PIN code'}),
    )
    country = forms.CharField(
        max_length=100,
        required=False,
        initial='India',
        label='Country',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Country'}),
    )
    save_address = forms.BooleanField(
        required=False,
        initial=True,
        label='Save this delivery address to my account',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )
    payment_method = forms.ChoiceField(
        choices=Order.PAYMENT_METHOD_CHOICES,
        initial=Order.PAYMENT_METHOD_COD,
        label='Payment method',
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if user is not None and user.is_authenticated:
            self.fields['saved_address'].queryset = user.addresses.all()
        if self.is_bound and self.data.get('saved_address'):
            # The selected saved address is authoritative; new-address fields
            # can remain prefilled without being required.
            for field_name in (
                'delivery_full_name',
                'delivery_phone',
                'house_number',
                'street',
                'landmark',
                'city',
                'state',
                'pin_code',
                'country',
            ):
                self.fields[field_name].required = False

    @staticmethod
    def _validate_phone(value):
        value = (value or '').strip()
        digits = re.sub(r'\D', '', value)
        if len(digits) < 10 or len(digits) > 15:
            raise forms.ValidationError('Enter a valid phone number with 10 to 15 digits.')
        return value

    def clean_phone(self):
        return self._validate_phone(self.cleaned_data.get('phone'))

    def clean_delivery_phone(self):
        value = self.cleaned_data.get('delivery_phone')
        if value:
            return self._validate_phone(value)
        return value

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()

    def clean(self):
        cleaned_data = super().clean()
        saved_address = cleaned_data.get('saved_address')
        if saved_address is not None and saved_address.user_id != getattr(self.user, 'pk', None):
            self.add_error('saved_address', 'Select one of your own saved addresses.')

        if saved_address is None:
            required_address_fields = {
                'delivery_full_name': 'Enter the delivery recipient name.',
                'delivery_phone': 'Enter the delivery phone number.',
                'house_number': 'Enter the house or flat number.',
                'street': 'Enter the street or locality.',
                'city': 'Enter the city.',
                'state': 'Enter the state.',
                'pin_code': 'Enter the PIN code.',
                'country': 'Enter the country.',
            }
            for field_name, message in required_address_fields.items():
                if not (cleaned_data.get(field_name) or '').strip():
                    self.add_error(field_name, message)

            country = (cleaned_data.get('country') or '').strip()
            pin_code = (cleaned_data.get('pin_code') or '').strip()
            if country.lower() in ('india', 'in') and pin_code and not re.fullmatch(r'\d{6}', pin_code):
                self.add_error('pin_code', 'Enter a valid 6-digit PIN code.')
            elif pin_code and not re.fullmatch(r'[A-Za-z0-9 -]{3,12}', pin_code):
                self.add_error('pin_code', 'Enter a valid PIN code.')
        return cleaned_data

    def customer_data(self):
        return {
            'name': self.cleaned_data['full_name'].strip(),
            'email': self.cleaned_data['email'],
            'phone': self.cleaned_data['phone'],
        }

    def shipping_data(self):
        saved_address = self.cleaned_data.get('saved_address')
        if saved_address is not None:
            return saved_address.snapshot()
        return {
            'full_name': self.cleaned_data['delivery_full_name'].strip(),
            'phone': self.cleaned_data['delivery_phone'].strip(),
            'house_number': self.cleaned_data['house_number'].strip(),
            'street': self.cleaned_data['street'].strip(),
            'landmark': (self.cleaned_data.get('landmark') or '').strip(),
            'city': self.cleaned_data['city'].strip(),
            'state': self.cleaned_data['state'].strip(),
            'pin_code': self.cleaned_data['pin_code'].strip(),
            'country': self.cleaned_data['country'].strip(),
        }
