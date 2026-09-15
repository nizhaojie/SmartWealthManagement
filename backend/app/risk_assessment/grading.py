from datetime import date


def grade_total_score(total: int) -> str:
    if total <= 24:
        return "C1"
    if total <= 34:
        return "C2"
    if total <= 44:
        return "C3"
    if total <= 54:
        return "C4"
    return "C5"


def valid_until_from(assessment_date: date) -> date:
    try:
        return assessment_date.replace(year=assessment_date.year + 1)
    except ValueError:
        return assessment_date.replace(year=assessment_date.year + 1, day=28)
