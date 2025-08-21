import datetime
from datetime import timedelta


def get_year_options() -> list[str]:
    """computes the "birth year" dropdown options for the intake form."""
    today = datetime.date.today()
    oneyear = timedelta(days=365)
    yearmin = (today - 123 * oneyear).year  # arbitrarilly set to 123 years old
    yearmax = (today - 18 * oneyear).year  # to ensure at least 18 year old
    yearopts = [str(year) for year in range(yearmin, yearmax)[::-1]]
    yearopts = ["Prefer not to say"] + yearopts

    return yearopts
