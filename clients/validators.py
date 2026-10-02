import re

from django.core.exceptions import ValidationError

_BUSINESS_ID_RE = re.compile(r"^(\d{6,7})-(\d)$")
_WEIGHTS = (7, 9, 10, 5, 8, 4, 2)


def normalize_business_id(value):
    """Return a Finnish business ID (Y-tunnus) as 1234567-8, or raise ValidationError.

    Old six-digit IDs get a leading zero. The check digit is verified.
    """
    value = (value or "").strip().replace(" ", "")
    if not value:
        return ""
    match = _BUSINESS_ID_RE.match(value)
    if not match:
        raise ValidationError("Business ID must look like 1234567-8.")
    digits, check = match.group(1).zfill(7), int(match.group(2))
    remainder = sum(int(d) * w for d, w in zip(digits, _WEIGHTS)) % 11
    if remainder == 1 or (0 if remainder == 0 else 11 - remainder) != check:
        raise ValidationError("Business ID check digit is not valid.")
    return f"{digits}-{check}"


def normalize_phone(value):
    """Return a phone number in international form (+358...), or raise ValidationError.

    Finnish local numbers such as 040 123 4567 become +358401234567.
    """
    value = re.sub(r"[\s\-().]", "", value or "")
    if not value:
        return ""
    if value.startswith("00"):
        value = "+" + value[2:]
    elif value.startswith("0"):
        value = "+358" + value[1:]
    if not re.fullmatch(r"\+\d{7,15}", value):
        raise ValidationError("Phone number is not valid.")
    return value
