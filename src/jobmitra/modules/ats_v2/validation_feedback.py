"""Safe field feedback: never return Pydantic input values or raw exceptions."""


def field_feedback(error):
    result = []
    for item in error.errors():
        path = [part for part in item["loc"] if isinstance(part, str) and part != "body"]
        field = path[-1] if path else ""
        kind, context = item["type"], item.get("ctx", {})
        message = {
            "full_name": "Please enter the candidate's full name.",
            "phone": "Please enter a valid mobile number.",
            "email": "Please enter a valid email address.",
            "company_id": "Please select an existing company.",
            "title": "Please enter a job title or working title.",
            "target_date": "Please enter a valid JD target date.",
        }.get(field, "Please check this field's value.")
        if kind == "missing":
            message = "Please complete this required field."
        elif kind in {"greater_than_equal", "less_than_equal"}:
            bound = context.get("ge" if kind == "greater_than_equal" else "le")
            if type(bound) in (int, float):
                direction = "at least" if kind == "greater_than_equal" else "no greater than"
                message = f"Please enter a value {direction} {bound:g}."
        elif kind in {"int_parsing", "int_from_float", "int_type"}:
            message = "Please enter a whole number."
        elif kind in {"string_too_long", "string_too_short"}:
            bound = context.get("max_length" if kind == "string_too_long" else "min_length")
            if type(bound) is int:
                direction = "at most" if kind == "string_too_long" else "at least"
                message = f"Please use {direction} {bound} characters."
        result.append({"field": field, "message": message})
    return result
