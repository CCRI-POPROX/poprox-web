import datetime
from datetime import timedelta


def get_year_options():
    today = datetime.date.today()
    oneyear = timedelta(days=365)
    yearmin = (today - 123 * oneyear).year  # arbitrarilly set to 100 years old
    yearmax = (today - 18 * oneyear).year  # to ensure at least 18 year old
    yearopts = [str(year) for year in range(yearmin, yearmax)[::-1]]
    yearopts = ["Prefer not to say"] + yearopts

    return yearopts


def validate(val, options):
    if isinstance(val, list):
        val = [v for v in val if v in options]
        if len(val) == 0:
            return None
    else:
        if val not in options:
            return None
    return val
