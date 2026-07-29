"""Multi-factor sign-in settings: enrolled devices & paper backup codes.

A person may enroll several devices, label them, revoke one, & keep the
rest. Enrolling a replacement phone is additive, so an account never
drops back to emailed codes during a swap. Every factor verifies with a
time-based one-time password (TOTP, RFC 6238) today; the same table
holds a security key or a push factor later.

Every state change demands proof of possession, so a hijacked session
can neither strip protection nor quietly add a device of its own. Each
form posts plain HTTP, so the whole flow works without JavaScript.
"""
from pyramid.view import view_config
from pyramid.httpexceptions import HTTPFound

from remarkbox.models.mfa_method import MfaMethod
from remarkbox.lib.totp import (
    new_secret,
    provisioning_uri,
    qr_svg,
    verify_code,
    derive_secret_key,
)
from remarkbox.views import user_required

MFA_ISSUER = "Remarkbox"


def _key(request):
    return derive_secret_key(request.registry.settings)


def _redirect(request):
    return HTTPFound("{}/u/settings/mfa".format(request.link_prefix))


def _context(request, user, qr=None, secret=None, backup_codes=None):
    return {
        "the_title": "Two-Factor Sign-in",
        "methods": user.mfa_methods,
        "mfa_enabled": user.mfa_enabled,
        "backup_codes_remaining": user.mfa_backup_codes_remaining,
        "backup_codes": backup_codes,
        "qr": qr,
        "secret": secret,
    }


@view_config(route_name="basic-mfa-setup", renderer="mfa-setup.j2")
@user_required()
def mfa_setup(request):
    user = request.user

    # Removing one device leaves every other one signing in, so an
    # account with two phones never falls back to emailed codes just
    # because one phone broke.
    if "revoke" in request.params:
        code = request.params.get("raw-otp", "")
        method_id = request.params.get("method-id", "")
        if user.verify_mfa(code, _key(request)):
            target = next(
                (m for m in user.mfa_methods if str(m.id) == method_id), None
            )
            if target:
                target.revoke()
                request.dbsession.add(target)
                request.dbsession.add(user)
                request.dbsession.flush()
                request.session.flash(
                    ("That device can no longer sign you in.", "success")
                )
            else:
                request.session.flash(("Device not found.", "error"))
        else:
            # A failed attempt still counts against the throttle.
            request.dbsession.add(user)
            request.session.flash(("Invalid code.", "error"))
        return _redirect(request)

    # Regenerating retires every code the user holds today, so it wants
    # the same proof bar as removing a device.
    if "regenerate" in request.params and user.mfa_enabled:
        code = request.params.get("raw-otp", "")
        if user.verify_mfa(code, _key(request)):
            codes = user.regenerate_backup_codes()
            request.dbsession.add(user)
            request.dbsession.flush()
            request.session.flash(
                (
                    "New backup codes generated. Your old codes no longer work.",
                    "success",
                )
            )
            # Show the paper codes exactly once.
            return _context(request, user, backup_codes=codes)
        request.dbsession.add(user)
        request.session.flash(("Invalid code.", "error"))
        return _redirect(request)

    # A pending secret lives in the session until one code proves the
    # app enrolled correctly; nothing reaches the database before that.
    if "cancel" in request.params:
        request.session.pop("mfa_pending_secret", None)
        return _redirect(request)

    if "confirm" in request.params:
        pending = request.session.get("mfa_pending_secret")
        code = request.params.get("raw-otp", "")
        label = (request.params.get("label", "") or "").strip()[:64]
        ok, _counter = verify_code(pending, code) if pending else (False, None)
        if ok:
            # An account holding a factor proves the existing one before
            # adding another; a first enrollment has nothing to prove
            # against.
            existing = user.mfa_methods
            proof = request.params.get("current-otp", "")
            if existing and not user.verify_mfa(proof, _key(request)):
                request.dbsession.add(user)
                request.session.flash(
                    ("Enter a code from a device you already enrolled.", "error")
                )
                return _redirect(request)

            method = MfaMethod(user.id, pending, _key(request), label=label)
            request.dbsession.add(method)
            codes = None
            if not existing:
                # First factor: mint the paper codes that back it up.
                codes = user.regenerate_backup_codes()
                request.dbsession.add(user)
            request.dbsession.flush()
            request.session.pop("mfa_pending_secret", None)
            request.session.flash(
                ("Device enrolled. It can sign you in now.", "success")
            )
            return _context(request, user, backup_codes=codes)
        request.session.flash(
            (
                "That code did not match. Scan the QR code again and enter a fresh code.",
                "error",
            )
        )

    if "enroll" in request.params or request.session.get("mfa_pending_secret"):
        pending = request.session.get("mfa_pending_secret")
        if not pending:
            pending = new_secret()
            request.session["mfa_pending_secret"] = pending
        uri = provisioning_uri(pending, user.email, MFA_ISSUER)
        return _context(request, user, qr=qr_svg(uri), secret=pending)

    return _context(request, user)
