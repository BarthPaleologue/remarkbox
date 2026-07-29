"""Authenticator-app enrollment: time-based one-time passwords (TOTP).

Optional passwordless login without email. Enrollment happens inside an
authenticated session: scan a QR code (or type the secret), prove it
with one code, save ten single-use paper backup codes. Login then asks
for a current app code instead of sending email.
"""
from pyramid.view import view_config
from pyramid.httpexceptions import HTTPFound

from remarkbox.lib.totp import (
    new_secret,
    provisioning_uri,
    qr_svg,
    verify_code,
    generate_backup_codes,
    hash_backup_codes,
)
from remarkbox.views import user_required

TOTP_ISSUER = "Remarkbox"


@view_config(route_name="basic-totp-setup", renderer="totp-setup.j2")
@user_required()
def totp_setup(request):
    user = request.user

    # Disable: requires a currently-valid app code or a paper backup
    # code, so a hijacked session cannot silently strip the protection.
    if "disable" in request.params:
        code = request.params.get("raw-otp", "")
        if user.verify_totp_or_backup(code):
            user.disable_totp()
            request.dbsession.add(user)
            request.dbsession.flush()
            request.session.flash(("Authenticator app disabled.", "success"))
        else:
            request.session.flash(("Invalid code.", "error"))
        return HTTPFound("{}/u/settings/totp".format(request.link_prefix))

    if user.totp_enabled:
        return {
            "the_title": "Authenticator App",
            "enabled": True,
            "qr": None,
            "secret": None,
            "backup_codes": None,
        }

    # Pending secret lives in the session until one code proves the app
    # enrolled correctly; nothing touches the database before that.
    pending = request.session.get("totp_pending_secret")
    if not pending:
        pending = new_secret()
        request.session["totp_pending_secret"] = pending

    if "activate" in request.params:
        code = request.params.get("raw-otp", "")
        ok, _counter = verify_code(pending, code)
        if ok:
            codes = generate_backup_codes()
            user.enable_totp(pending, hash_backup_codes(codes))
            request.dbsession.add(user)
            request.dbsession.flush()
            request.session.pop("totp_pending_secret", None)
            request.session.flash(("Authenticator app enabled.", "success"))
            # Show the paper codes exactly once.
            return {
                "the_title": "Authenticator App",
                "enabled": True,
                "qr": None,
                "secret": None,
                "backup_codes": codes,
            }
        request.session.flash(
            (
                "That code did not match. Scan the QR code again and enter a fresh code.",
                "error",
            )
        )

    uri = provisioning_uri(pending, user.email, TOTP_ISSUER)
    return {
        "the_title": "Authenticator App",
        "enabled": False,
        "qr": qr_svg(uri),
        "secret": pending,
        "backup_codes": None,
    }
