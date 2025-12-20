from hashlib import md5

from ago import human

from datetime import datetime


def timestamp_to_datetime(timestamp):
    """Accepts a timestamp and returns a date string"""
    return datetime.fromtimestamp(timestamp / 1000.0)


def timestamp_to_date_string(timestamp):
    return timestamp_to_datetime(timestamp).strftime("%b %d, %Y %I:%M %P")


def timestamp_to_date(timestamp):
    """Accepts a timestamp and returns a short date string (e.g., 'Dec 19, 2024')"""
    return timestamp_to_datetime(timestamp).strftime("%b %d, %Y")


def timestamp_to_ago_string(timestamp):
    """Accepts a timestamp and returns a human readable string"""
    return human(timestamp_to_datetime(timestamp), 2, abbreviate=True)


def gravatar_client(email, size=48, rating="g", default="retro", force_default=False):
    """Return a gravatar API URI."""
    query_params = ["s={}".format(size), "r={}".format(rating), "d={}".format(default)]
    if force_default:
        query_params.append("f=y")
    uri = "https://secure.gravatar.com/avatar/{0}?{1}"

    try:
        # Python 2.
        email_md5 = md5(email).hexdigest()
    except TypeError:
        # Python 3.
        email_md5 = md5(email.encode("utf-8")).hexdigest()

    return uri.format(email_md5, "&".join(query_params))
