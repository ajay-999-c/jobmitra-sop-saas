"""Pure normalization shared by ORM writes and the offline workbook cleaner."""

import unicodedata


def company_name_key(value: str) -> str:
    """Compare names without changing punctuation, legal suffixes or word order."""
    if not isinstance(value, str):
        raise ValueError("Company name must be text")
    key = " ".join(unicodedata.normalize("NFKC", value).split()).casefold()
    if not key:
        raise ValueError("Company name must not be blank")
    return key


def distinct_text_values(values: list[str]) -> list[str]:
    """Preserve string identifiers and leading zeroes; never guess missing data."""
    if not isinstance(values, list):
        raise ValueError("Array values must be a list of nonblank strings")
    result = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Array values must be nonblank strings")
        value = value.strip()
        if value not in result:
            result.append(value)
    return result
