from django import forms
from django_recaptcha.fields import ReCaptchaField
from django_recaptcha.widgets import ReCaptchaV2Checkbox
from .models import ModelSpecification, Vendor
from .widgets import KeyValueField
from django.conf import settings

class SpecificationAdminForm(forms.ModelForm):
    """Custom form for Specification admin with key-value widget"""

    specs = KeyValueField(
        required=False,
        help_text="Add technical specifications as key-value pairs. Click + to add more fields.",
    )

    class Meta:
        model = ModelSpecification
        fields = "__all__"


class VendorAdminForm(forms.ModelForm):
    """Custom form for Vendor admin with key-value widget for details"""

    details = KeyValueField(
        required=False,
        help_text="Add vendor details as key-value pairs. Click + to add more fields.",
    )

    class Meta:
        model = Vendor
        fields = "__all__"


class LoginCaptchaForm(forms.Form):
    captcha = ReCaptchaField(widget=ReCaptchaV2Checkbox())
