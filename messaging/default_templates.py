"""The firm's starter templates. Every one uses {name}, {company}, {business_id} and {due_date}."""

TEMPLATES = [
    {
        "title": "Receipts reminder",
        "channel": "email",
        "subject_fi": "Muistutus: kuitit {due_date} mennessä ({company})",
        "body_fi": (
            "Hei {name},\n\n"
            "muistathan toimittaa yrityksen {company} (Y-tunnus {business_id}) kuluvan kuukauden kuitit "
            "ja tositteet meille {due_date} mennessä.\n\n"
            "Jos sinulla on kysyttävää, vastaa tähän viestiin.\n\n"
            "Ystävällisin terveisin\nTilitoimisto"
        ),
        "subject_en": "Reminder: receipts by {due_date} ({company})",
        "body_en": (
            "Hello {name},\n\n"
            "please send us this month's receipts and documents for {company} (business ID {business_id}) "
            "by {due_date}.\n\n"
            "If you have any questions, just reply to this email.\n\n"
            "Best regards\nTilitoimisto"
        ),
    },
    {
        "title": "VAT return deadline",
        "channel": "email",
        "subject_fi": "Arvonlisäveroilmoitus erääntyy {due_date} ({company})",
        "body_fi": (
            "Hei {name},\n\n"
            "yrityksen {company} (Y-tunnus {business_id}) arvonlisäveroilmoitus ja -maksu erääntyvät {due_date}.\n\n"
            "Lähetäthän puuttuvat myynti- ja ostotositteet viimeistään viikkoa ennen eräpäivää, "
            "jotta ehdimme tehdä ilmoituksen ajallaan.\n\n"
            "Terveisin\nTilitoimisto"
        ),
        "subject_en": "VAT return due {due_date} ({company})",
        "body_en": (
            "Hello {name},\n\n"
            "the VAT return and payment for {company} (business ID {business_id}) are due on {due_date}.\n\n"
            "Please send any missing sales and purchase documents at least a week before the due date, "
            "so we can file on time.\n\n"
            "Regards\nTilitoimisto"
        ),
    },
    {
        "title": "Year-end documents",
        "channel": "email",
        "subject_fi": "Tilinpäätösaineisto {due_date} mennessä ({company})",
        "body_fi": (
            "Hei {name},\n\n"
            "aloitamme yrityksen {company} (Y-tunnus {business_id}) tilinpäätöksen. Toimitathan meille "
            "{due_date} mennessä:\n\n"
            "- tiliotteet tilikauden viimeiseltä päivältä\n"
            "- varasto- ja keskeneräisten töiden tiedot\n"
            "- avoimet myynti- ja ostolaskut\n"
            "- lainojen saldot\n\n"
            "Kiitos!\n\nTerveisin\nTilitoimisto"
        ),
        "subject_en": "Year-end documents by {due_date} ({company})",
        "body_en": (
            "Hello {name},\n\n"
            "we are starting the financial statements for {company} (business ID {business_id}). "
            "Please send us by {due_date}:\n\n"
            "- bank statements for the last day of the financial year\n"
            "- stock and work-in-progress figures\n"
            "- open sales and purchase invoices\n"
            "- loan balances\n\n"
            "Thank you!\n\nRegards\nTilitoimisto"
        ),
    },
    {
        "title": "Documents reminder",
        "channel": "sms",
        "subject_fi": "",
        "body_fi": "Hei {name}! Muistathan toimittaa yrityksen {company} ({business_id}) tositteet {due_date} mennessä. T. Tilitoimisto",
        "subject_en": "",
        "body_en": "Hi {name}! Please send the documents for {company} ({business_id}) by {due_date}. Regards, Tilitoimisto",
    },
    {
        "title": "Receipts reminder",
        "channel": "sms",
        "subject_fi": "",
        "body_fi": "Hei {name}! Muistathan lähettää yrityksen {company} ({business_id}) kuitit {due_date} mennessä. T. Tilitoimisto",
        "subject_en": "",
        "body_en": "Hi {name}! Please send the receipts for {company} ({business_id}) by {due_date}. Regards, Tilitoimisto",
    },
    {
        "title": "VAT return deadline",
        "channel": "sms",
        "subject_fi": "",
        "body_fi": "Hei {name}! Yrityksen {company} ({business_id}) ALV-ilmoitus erääntyy {due_date}. Lähetäthän puuttuvat tositteet pian. T. Tilitoimisto",
        "subject_en": "",
        "body_en": "Hi {name}! The VAT return for {company} ({business_id}) is due {due_date}. Please send missing documents soon. Regards, Tilitoimisto",
    },
    {
        "title": "Year-end documents",
        "channel": "sms",
        "subject_fi": "",
        "body_fi": "Hei {name}! Tilinpäätöstä varten tarvitsemme yrityksen {company} ({business_id}) aineiston {due_date} mennessä. Ohjeet sähköpostissa. T. Tilitoimisto",
        "subject_en": "",
        "body_en": "Hi {name}! For the year-end we need the documents for {company} ({business_id}) by {due_date}. Details by email. Regards, Tilitoimisto",
    },
]
