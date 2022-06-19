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


def send_verification_digits_to_email(request, to_email, raw_digits):
    """
    Send email with raw_digits a user may pass to verify & authenticate.

    request
      the request (of the successful log in attempt)

    to_email
      the email address to send the raw_digits

    raw_digits:
      the raw (unencrypted) digits the user may use to verify & authenticate.
    """
    subject = "Verification Code - {}".format(raw_digits)

    message_text = WELCOME_1_TEXT.format(raw_digits)
    message_html = WELCOME_1_HTML.format(subject, raw_digits)

    if not request.user.verified:
        message_text = WELCOME_1_TEXT.format(raw_digits)
        message_html = WELCOME_1_HTML.format(subject, raw_digits)
    else:
        message_text = WELCOME_2_TEXT.format(raw_digits)
        message_html = WELCOME_2_HTML.format(subject, raw_digits)

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
