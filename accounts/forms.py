from django import forms
from django.contrib.auth.password_validation import validate_password

from .models import User


class TeamMemberForm(forms.ModelForm):
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(render_value=False),
        required=False,
        help_text="At least 10 characters. Leave empty to keep the current one.",
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "role", "is_active"]
        labels = {"is_active": "Active (can log in)"}
        help_texts = {"is_active": "Untick to block login. History is kept."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        if self.instance.pk is None:
            self.fields["password"].required = True
            self.fields["password"].help_text = "At least 10 characters."

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if password:
            validate_password(password, self.instance)
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("password"):
            user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user
