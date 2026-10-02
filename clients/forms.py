from django import forms
from django.contrib.auth import get_user_model

from .models import Client
from .validators import normalize_business_id, normalize_phone

User = get_user_model()


def active_users():
    return User.objects.filter(is_active=True).order_by("first_name", "last_name", "email")


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = [
            "name",
            "business_id",
            "company_type",
            "email",
            "phone",
            "language",
            "profession",
            "notes",
            "owner",
            "opted_out",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None and user.is_admin:
            self.fields["owner"].queryset = active_users()
            self.fields["owner"].empty_label = "Unassigned"
            self.fields["owner"].label = "Team member"
        else:
            # Team members can edit their own clients but never change who owns them.
            del self.fields["owner"]

    def clean_business_id(self):
        value = normalize_business_id(self.cleaned_data.get("business_id"))
        if value and Client.objects.filter(business_id=value).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Another client already has this business ID.")
        return value

    def clean_phone(self):
        return normalize_phone(self.cleaned_data.get("phone"))

    def clean_email(self):
        return (self.cleaned_data.get("email") or "").strip().lower()


class ImportUploadForm(forms.Form):
    file = forms.FileField(
        label="CSV or Excel file",
        help_text="First row must be column names (Finnish names work too). Up to 5000 rows.",
    )

    def clean_file(self):
        f = self.cleaned_data["file"]
        name = f.name.lower()
        if not (name.endswith(".csv") or name.endswith(".xlsx")):
            raise forms.ValidationError("Please upload a .csv or .xlsx file.")
        if f.size > 5 * 1024 * 1024:
            raise forms.ValidationError("The file is larger than 5 MB.")
        return f


class ImportMappingForm(forms.Form):
    """One select per client field; each offers the columns found in the file."""

    def __init__(self, *args, headers, fields, initial_mapping=None, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("", "(do not import)")] + [(str(i), h or f"Column {i + 1}") for i, h in enumerate(headers)]
        for key, label, required in fields:
            self.fields[key] = forms.ChoiceField(
                label=label, choices=choices, required=required, initial=(initial_mapping or {}).get(key, "")
            )
        self.fields["owner"] = forms.ModelChoiceField(
            label="Assign imported clients to",
            queryset=active_users(),
            required=False,
            empty_label="Leave unassigned",
        )

    def mapping(self):
        return {k: int(v) for k, v in self.cleaned_data.items() if k != "owner" and v not in ("", None)}
