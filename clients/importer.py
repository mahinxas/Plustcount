"""Client import from CSV or Excel: read, map columns, validate, then save."""

import csv
import io

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from openpyxl import load_workbook

from .models import Client, ClientAssignment
from .validators import normalize_business_id, normalize_phone

MAX_ROWS = 5000

# (key, label, required)
FIELDS = [
    ("name", "Name", True),
    ("business_id", "Business ID (Y-tunnus)", False),
    ("company_type", "Company type", False),
    ("email", "Email", False),
    ("phone", "Phone", False),
    ("language", "Language", False),
    ("profession", "Profession", False),
    ("notes", "Notes", False),
]

# Header names we recognise automatically, in English and Finnish.
_HEADER_ALIASES = {
    "name": {"name", "nimi", "client", "asiakas", "company", "yritys", "company name", "yrityksen nimi"},
    "business_id": {"business id", "business_id", "y-tunnus", "ytunnus", "y tunnus", "vat id"},
    "company_type": {"company type", "type", "yhtiömuoto", "yritysmuoto", "tyyppi"},
    "email": {"email", "e-mail", "sähköposti", "sahkoposti", "email address"},
    "phone": {"phone", "puhelin", "mobile", "puhelinnumero", "gsm", "matkapuhelin"},
    "language": {"language", "kieli", "lang"},
    "profession": {"profession", "industry", "ammatti", "toimiala", "ala"},
    "notes": {"notes", "note", "muistiinpanot", "lisätiedot", "huomiot"},
}

_COMPANY_TYPES = {
    "oy": Client.CompanyType.OY,
    "osakeyhtiö": Client.CompanyType.OY,
    "tmi": Client.CompanyType.TOIMINIMI,
    "toiminimi": Client.CompanyType.TOIMINIMI,
    "yksityishenkilö": Client.CompanyType.PERSON,
    "person": Client.CompanyType.PERSON,
    "private person": Client.CompanyType.PERSON,
}

_LANGUAGES = {
    "": Client.Language.FI,
    "fi": Client.Language.FI,
    "suomi": Client.Language.FI,
    "finnish": Client.Language.FI,
    "en": Client.Language.EN,
    "english": Client.Language.EN,
    "englanti": Client.Language.EN,
}


_PROFESSIONS = {
    "delivery rider": Client.Profession.DELIVERY_RIDER,
    "delivery": Client.Profession.DELIVERY_RIDER,
    "courier": Client.Profession.DELIVERY_RIDER,
    "lähetti": Client.Profession.DELIVERY_RIDER,
    "ruokalähetti": Client.Profession.DELIVERY_RIDER,
    "taxi": Client.Profession.TAXI,
    "taksi": Client.Profession.TAXI,
    "restaurant": Client.Profession.RESTAURANT,
    "ravintola": Client.Profession.RESTAURANT,
}


class ImportFileError(Exception):
    pass


def read_table(uploaded_file):
    """Return (headers, rows) where every cell is a stripped string."""
    name = uploaded_file.name.lower()
    raw = uploaded_file.read()
    if name.endswith(".xlsx"):
        rows = _read_xlsx(raw)
    else:
        rows = _read_csv(raw)
    rows = [r for r in rows if any(cell for cell in r)]
    if not rows:
        raise ImportFileError("The file is empty.")
    headers, body = rows[0], rows[1:]
    if len(body) > MAX_ROWS:
        raise ImportFileError(f"The file has {len(body)} rows. The maximum is {MAX_ROWS}.")
    width = len(headers)
    body = [(r + [""] * width)[:width] for r in body]
    return headers, body


def _read_csv(raw):
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ImportFileError("Could not read the file. Please save it as UTF-8 CSV.")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text), dialect)]


def _read_xlsx(raw):
    try:
        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises many different types for bad files
        raise ImportFileError("Could not read the Excel file.") from exc
    sheet = workbook.worksheets[0]
    rows = []
    for row in sheet.iter_rows(values_only=True):
        rows.append(["" if v is None else str(v).strip() for v in row])
        if len(rows) > MAX_ROWS + 1:
            break
    workbook.close()
    return rows


def guess_mapping(headers):
    mapping = {}
    for index, header in enumerate(headers):
        normalized = header.strip().lower()
        for key, aliases in _HEADER_ALIASES.items():
            if key not in mapping and normalized in aliases:
                mapping[key] = str(index)
    return mapping


def _clean_row(values):
    """Turn raw strings into client field values. Returns (data, errors)."""
    errors = []
    data = {"name": values.get("name", "").strip()[:200]}
    if not data["name"]:
        errors.append("Name is missing.")

    try:
        data["business_id"] = normalize_business_id(values.get("business_id", ""))
    except ValidationError as exc:
        errors.append(exc.messages[0])
        data["business_id"] = ""

    email = values.get("email", "").strip().lower()
    if email:
        try:
            validate_email(email)
        except ValidationError:
            errors.append(f"Email '{email}' is not valid.")
            email = ""
    data["email"] = email

    try:
        data["phone"] = normalize_phone(values.get("phone", ""))
    except ValidationError:
        errors.append(f"Phone '{values.get('phone')}' is not valid.")
        data["phone"] = ""

    language = values.get("language", "").strip().lower()
    if language not in _LANGUAGES:
        errors.append(f"Language '{language}' is not Finnish or English.")
    data["language"] = _LANGUAGES.get(language, Client.Language.FI)

    data["company_type"] = _COMPANY_TYPES.get(values.get("company_type", "").strip().lower(), Client.CompanyType.OTHER)
    data["profession"] = _PROFESSIONS.get(values.get("profession", "").strip().lower(), Client.Profession.OTHER)
    data["notes"] = values.get("notes", "").strip()
    return data, errors


def validate_rows(rows, mapping):
    """Validate every row and flag duplicates against the database and the file itself.

    Returns a list of dicts: {"line", "data", "errors", "duplicate"}. Line numbers
    match the spreadsheet (header is line 1).
    """
    results = []
    for offset, row in enumerate(rows):
        values = {key: row[index] for key, index in mapping.items() if index < len(row)}
        data, errors = _clean_row(values)
        results.append({"line": offset + 2, "data": data, "errors": errors, "duplicate": ""})

    business_ids = {r["data"]["business_id"] for r in results if r["data"]["business_id"]}
    emails = {r["data"]["email"] for r in results if r["data"]["email"]}
    existing_ids = set(
        Client.objects.filter(business_id__in=business_ids).values_list("business_id", flat=True)
    )
    existing_emails = set(Client.objects.filter(email__in=emails).values_list("email", flat=True))

    seen_ids, seen_emails = set(), set()
    for result in results:
        bid, email = result["data"]["business_id"], result["data"]["email"]
        if bid and bid in existing_ids:
            result["duplicate"] = f"A client with business ID {bid} already exists."
        elif email and email in existing_emails:
            result["duplicate"] = f"A client with email {email} already exists."
        elif bid and bid in seen_ids:
            result["duplicate"] = f"Business ID {bid} appears earlier in the file."
        elif email and email in seen_emails:
            result["duplicate"] = f"Email {email} appears earlier in the file."
        if bid:
            seen_ids.add(bid)
        if email:
            seen_emails.add(email)
    return results


@transaction.atomic
def save_rows(results, actor, owner=None):
    """Create clients for valid, non-duplicate rows. Returns the number created."""
    to_create = [Client(**r["data"], owner=owner) for r in results if not r["errors"] and not r["duplicate"]]
    created = Client.objects.bulk_create(to_create)
    if owner is not None:
        ClientAssignment.objects.bulk_create(
            ClientAssignment(client=c, from_user=None, to_user=owner, changed_by=actor) for c in created
        )
    return len(created)
