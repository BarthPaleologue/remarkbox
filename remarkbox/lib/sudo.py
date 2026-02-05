from remarkbox.models.sudo_otp import create_sudo_otp
from remarkbox.lib.mail import send_sudo_otp_email


def request_sudo_otp(request, action_key, action_description):
    """Generate a sudo OTP code, email it to the current user, and return the code."""
    code = create_sudo_otp(
        request.dbsession,
        action_key,
        action_description,
        client_ip=str(request.client_addr),
    )
    send_sudo_otp_email(request, request.user.email, action_description, code)
    return code
