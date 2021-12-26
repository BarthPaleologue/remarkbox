from pyramid.view import view_config

from pyramid.httpexceptions import HTTPFound, HTTPBadRequest

from remarkbox.views import user_required

from remarkbox.lib.mail import send_operator_email

from remarkbox.models import PayWhatYouCan


@view_config(route_name="billing", renderer="billing.j2")
@user_required(
    flash_msg="Thank you for helping us out, Please verify your email in the form below!",
    flash_level="info",
    return_to_route_name="billing"
)
def billing(request):
    return {"the_title": "Payment Preferences"}


@view_config(route_name="add-card")
@user_required()
def add_card(request):
    # try to get the return_to uri from posted parameters.
    return_to = request.params.get("return-to", "/billing")
    try:
        source = request.stripe_customer.sources.create(
            source=request.params.get("stripeToken")
        )
        request.stripe_customer.default_source = source
        request.session.flash(("You saved a new card.", "success"))
        # TODO: this is very temporary just as a stop gap for me to stay on top of new customers.
        send_operator_email(
            request,
            "A user (hopefully a new one!) added a new card to their Stripe customer account. Log into Stripe and follow up to close the sale!",
        )
    except request.stripe.error.CardError as e:
        body = e.json_body
        err = body.get("error", {})
        request.session.flash((err.get("message"), "error"))
    request.stripe_customer.save()
    return HTTPFound(return_to)


@view_config(route_name="confirm-update-card", renderer="update-card.j2")
@user_required()
def confirm_update_card(request):
    card_id = request.matchdict.get("card_id")
    card = request.stripe_customer.sources.retrieve(card_id)
    action = request.matchdict.get("action")
    action_human = action.replace("-", " ")
    button_class = "red-button" if action == "delete-card" else "blue-button"
    return {
        "card": card,
        "card_id": card_id,
        "action": action,
        "action_human": action_human,
        "button_class": button_class,
        "the_title": action_human.title(),
    }


@view_config(route_name="update-card")
@user_required()
def update_card(request):
    action = request.params.get("action", None)
    card_id = request.params.get("card_id")
    if action not in ["make-card-active", "delete-card"]:
        return HTTPBadRequest
    if "delete-card" == action:
        request.stripe_customer.sources.retrieve(card_id).delete()
        request.session.flash(("You deleted that card.", "success"))
    if "make-card-active" == action:
        request.stripe_customer.default_source = card_id
        request.session.flash(("You set the active card.", "success"))
    request.stripe_customer.save()
    return HTTPFound("/billing")


@view_config(route_name="pay-what-you-can")
@user_required()
def pay_what_you_can(request):
    frequency = request.params.get("frequency", None)
    amount = request.params.get("amount", None)
    if frequency is None or amount is None:
        request.session.flash(("You must put a value for both frequency and amount.", "error"))
    elif request.user.pay_what_you_can:
        request.user.pay_what_you_can.update(frequency, amount)
        request.session.flash(("You updated your contribution preferences.", "success"))
    else:
        request.user.pay_what_you_can = PayWhatYouCan(request.user, frequency, amount)
        request.session.flash(("You updated your contribution preferences.", "success"))
    return HTTPFound("/billing")
