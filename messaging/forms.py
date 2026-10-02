from django import forms
from django.utils import timezone

from . import personalize, sms
from .models import Channel, MessageTemplate

LANG_NAMES = {"fi": "Finnish", "en": "English"}


def _check_sms_length(form, *field_names):
    for name in field_names:
        text = form.cleaned_data.get(name) or ""
        parts = sms.segments(text)
        if parts > sms.MAX_PARTS:
            form.add_error(name, f"Too long: {parts} SMS. Keep it within {sms.MAX_PARTS} SMS.")


def _check_placeholders(form, *field_names):
    for name in field_names:
        unknown = personalize.unknown_placeholders(form.cleaned_data.get(name, ""))
        if unknown:
            form.add_error(
                name,
                "Unknown field(s): "
                + ", ".join("{" + u + "}" for u in unknown)
                + ". Available: "
                + ", ".join("{" + f + "}" for f in personalize.FIELDS),
            )


class TemplateForm(forms.ModelForm):
    class Meta:
        model = MessageTemplate
        fields = ["title", "channel", "subject_fi", "body_fi", "subject_en", "body_en"]
        widgets = {
            "body_fi": forms.Textarea(attrs={"rows": 8}),
            "body_en": forms.Textarea(attrs={"rows": 8}),
            "channel": forms.RadioSelect,
        }

    def clean(self):
        cleaned = super().clean()
        is_sms = cleaned.get("channel") == Channel.SMS
        if not (cleaned.get("body_fi") or cleaned.get("body_en")):
            raise forms.ValidationError("Write at least one language version.")
        if is_sms:
            cleaned["subject_fi"] = cleaned["subject_en"] = ""  # SMS have no subject
            _check_sms_length(self, "body_fi", "body_en")
        else:
            for lang in ("fi", "en"):
                if cleaned.get(f"body_{lang}") and not cleaned.get(f"subject_{lang}"):
                    self.add_error(f"subject_{lang}", "A subject is needed when the message is written.")
        _check_placeholders(self, "subject_fi", "body_fi", "subject_en", "body_en")
        return cleaned


class ComposeForm(forms.Form):
    # The view reads the channel itself (default email); the field is here to draw the switch.
    channel = forms.ChoiceField(choices=Channel.choices, initial=Channel.EMAIL, widget=forms.RadioSelect, required=False)
    recipients = forms.CharField(widget=forms.HiddenInput)
    idempotency_key = forms.CharField(widget=forms.HiddenInput, max_length=64)
    template = forms.ModelChoiceField(
        queryset=MessageTemplate.objects.all(), required=False, empty_label="Write a new message"
    )
    due_date = forms.DateField(
        label="Due date",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        help_text="Shown as 5.4.2027",
    )
    subject_fi = forms.CharField(label="Subject (Finnish)", max_length=200, required=False)
    body_fi = forms.CharField(label="Message (Finnish)", widget=forms.Textarea(attrs={"rows": 9}), required=False)
    subject_en = forms.CharField(label="Subject (English)", max_length=200, required=False)
    body_en = forms.CharField(label="Message (English)", widget=forms.Textarea(attrs={"rows": 9}), required=False)

    def __init__(self, *args, languages=(), channel=Channel.EMAIL, **kwargs):
        super().__init__(*args, **kwargs)
        self.languages = set(languages)
        self.channel = channel
        self.fields["template"].queryset = MessageTemplate.objects.filter(channel=channel)
        self.fields["due_date"].widget.attrs["min"] = timezone.localdate().isoformat()
        if channel == Channel.SMS:
            for lang, name in LANG_NAMES.items():
                self.fields[f"body_{lang}"].label = f"SMS ({name})"
                self.fields[f"body_{lang}"].widget.attrs["rows"] = 5
        # A language version is required only when some recipients read that language.
        parts = ("body",) if channel == Channel.SMS else ("subject", "body")
        for lang in self.languages:
            for part in parts:
                field = self.fields[f"{part}_{lang}"]
                field.required = True
                field.error_messages["required"] = f"Needed for clients who read {LANG_NAMES[lang]}."

    def clean_due_date(self):
        due = self.cleaned_data.get("due_date")
        if due and due < timezone.localdate():
            raise forms.ValidationError("Choose today or a later date.")
        return due

    def clean(self):
        cleaned = super().clean()
        if self.channel == Channel.SMS:
            cleaned["subject_fi"] = cleaned["subject_en"] = ""
            _check_sms_length(self, "body_fi", "body_en")
        _check_placeholders(self, "subject_fi", "body_fi", "subject_en", "body_en")
        uses_due_date = any(
            "{due_date}" in (cleaned.get(f) or "") for f in ("subject_fi", "body_fi", "subject_en", "body_en")
        )
        if uses_due_date and not cleaned.get("due_date"):
            self.add_error("due_date", "The message uses {due_date}; please fill it in.")
        return cleaned

    def content(self):
        content = {k: (self.cleaned_data.get(k) or "").strip() for k in ("subject_fi", "body_fi", "subject_en", "body_en")}
        due = self.cleaned_data.get("due_date")
        # Finnish date style, the same in both languages: 5.4.2027
        content["due_date"] = f"{due.day}.{due.month}.{due.year}" if due else ""
        return content
