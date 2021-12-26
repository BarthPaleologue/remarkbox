from miscutils.mail import send_pyramid_email

# quote email address in OTP so that a plus address
# is not  decoded as a space during authentication.
try:
    # Python 2.
    from urllib import quote_plus
except ImportError:
    # Python 3.
    from urllib.parse import quote_plus

from remarkbox.lib.mail_messages import (
    WELCOME_1_TEXT,
    WELCOME_1_HTML,
    WELCOME_2_TEXT,
    WELCOME_2_HTML,
    OPERATOR_HTML,
)

from jinja2 import Environment, PackageLoader, select_autoescape

jinja2_env = Environment(
    loader=PackageLoader("remarkbox", "templates"),
    autoescape=select_autoescape(["html", "xml"]),
)


def send_otp_email(request, to_email, raw_otp, return_to):
    """
    Send email with OTP (one time password) link.

    request
      the request (of the successful log in attempt)

    to_email
      the email address to send the OTP link

    raw_otp
      the raw (unencrypted) one time password

    return_to
      the URI to return the user on successful authentication
    """

    query_params = [
        "email={}".format(quote_plus(to_email)),
        "raw-otp={}".format(raw_otp),
    ]

    if return_to:
        query_params.append("return-to={}".format(return_to))

    link = "{0}/join-or-log-in?{1}".format(request.host_url, "&".join(query_params))

    subject = "Magic sign-in link for comments"

    if not request.user.verified:
        message_text = WELCOME_1_TEXT.format(link)
        message_html = WELCOME_1_HTML.format(subject, link)
    else:
        message_text = WELCOME_2_TEXT.format(link)
        message_html = WELCOME_2_HTML.format(subject, link)

    send_pyramid_email(request, to_email, subject, message_text, message_html)


def send_operator_email(request, msg):
    send_pyramid_email(
        request,
        "russell.ballestrini@gmail.com",
        msg,
        msg,
        OPERATOR_HTML.format(msg),
    )


def send_template_email(
    request, to_email, subject, text_template_name, html_template_name, context
):
    text_template = jinja2_env.get_template(text_template_name)
    html_template = jinja2_env.get_template(html_template_name)
    send_pyramid_email(
        request,
        to_email,
        subject,
        text_template.render(**context),
        html_template.render(**context),
    )
