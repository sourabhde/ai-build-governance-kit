"""PII patterns shared by the policy assistant (rag.py) and the runtime guard."""
import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"\+?\d[\d\s\-‐‑]{8,}\d")  # also catches no-break spaces/hyphens
COMPANY_EMAIL_DOMAIN = "@company.example"  # the company's own contact addresses are not personal data


def redact_pii(text: str) -> str:
    text = EMAIL.sub(lambda m: m.group() if m.group().endswith(COMPANY_EMAIL_DOMAIN) else "[email redacted]", text)
    return PHONE.sub("[phone redacted]", text)
