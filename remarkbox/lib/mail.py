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

import dkim

import smtplib

from email.mime.multipart import MIMEMultipart

from email.mime.text import MIMEText

# catch socket errors when postfix isn't running...
from socket import error as socket_error

import logging

log = logging.getLogger(__name__)

from jinja2 import Environment, PackageLoader, select_autoescape

jinja2_env = Environment(
    loader=PackageLoader("remarkbox", "templates"),
    autoescape=select_autoescape(["html", "xml"]),
)


def send_email(
    to_email,
    sender_email,
    subject,
    message_text,
    message_html,
    relay="localhost",
    dkim_private_key_path="",
    dkim_selector="",
    dkim_signature_algorithm="ed25519-sha256",
    debug_mode=False,
):
    # the `email` library assumes it is working with string objects.
    # the `dkim` library assumes it is working with byte objects.
    # this function performs the acrobatics to make them both happy.
    if isinstance(message_text, bytes):
        # needed for Python 3.
        message_text = message_text.decode()

    if isinstance(message_html, bytes):
        # needed for Python 3.
        message_html = message_html.decode()

    sender_domain = sender_email.split("@")[-1]
    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText(message_text, "plain"))
    msg.attach(MIMEText(message_html, "html"))
    msg["To"] = to_email
    msg["From"] = sender_email
    msg["Subject"] = subject

    try:
        # Python 3 libraries expect bytes.
        msg_data = msg.as_bytes()
    except:
        # Python 2 libraries expect strings.
        msg_data = msg.as_string()

    if dkim_private_key_path and dkim_selector:
        try:
            # the dkim library uses regex on byte strings so everything
            # needs to be encoded from strings to bytes.
            with open(dkim_private_key_path) as fh:
                dkim_private_key = fh.read()
            headers = [b"To", b"From", b"Subject"]
            sig = dkim.sign(
                message=msg_data,
                selector=str(dkim_selector).encode(),
                domain=sender_domain.encode(),
                privkey=dkim_private_key.encode(),
                include_headers=headers,
                signature_algorithm=dkim_signature_algorithm.encode(),
            )
            # add the dkim signature to the email message headers.
            # decode the signature back to string_type because later on
            # the call to msg.as_string() performs it's own bytes encoding...
            msg["DKIM-Signature"] = sig[len("DKIM-Signature: ") :].decode()

            try:
                # Python 3 libraries expect bytes.
                msg_data = msg.as_bytes()
            except:
                # Python 2 libraries expect strings.
                msg_data = msg.as_string()
        except Exception as e:
            if debug_mode:
                log.error(f"DKIM signing failed: {str(e)}")
            raise

    try:
        s = smtplib.SMTP(relay)
        s.sendmail(sender_email, [to_email], msg_data)
        s.quit()
        return msg

    except (socket_error, smtplib.SMTPException) as e:
        error_msg = f"Failed to send email: {str(e)}"

        if debug_mode:
            # Log the error first for quick scanning
            log.error(error_msg)
            # Then log the email details
            log.info(
                f"""

Email Contents:
To: {to_email}
From: {sender_email}
Subject: {subject}

Text Content:
{message_text}

HTML Content:
{message_html}
            """
            )

        if not debug_mode:
            raise
        return None


def send_pyramid_email(request, to_email, subject, message_text, message_html):
    """Thin wrapper around `send_email` to customise settings using request object."""
    default_sender = "no-reply@{}".format(request.domain)
    sender_email = request.app.get("email.sender", default_sender)
    subject = "{} | {}".format(
        subject, request.app.get("email.subject_postfix", request.domain)
    )
    relay = request.app.get("email.relay", "localhost")
    dkim_private_key_path = request.app.get("email.dkim_private_key_path", "")
    dkim_selector = request.app.get("email.dkim_selector", "")
    dkim_signature_algorithm = request.app.get(
        "email.dkim_signature_algorithm", "ed25519-sha256"
    )

    send_email(
        to_email,
        sender_email,
        subject,
        message_text,
        message_html,
        relay,
        dkim_private_key_path,
        dkim_selector,
        dkim_signature_algorithm,
        request.debug_mode,
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

    if request.user and request.user.verified:
        message_text = WELCOME_2_TEXT.format(raw_digits)
        message_html = WELCOME_2_HTML.format(subject, raw_digits)
    else:
        message_text = WELCOME_1_TEXT.format(raw_digits)
        message_html = WELCOME_1_HTML.format(subject, raw_digits)

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
