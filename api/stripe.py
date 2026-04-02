"""
Stripe integration for Captio.

Exposes endpoints to create a Stripe Checkout session and receive webhooks.
"""

from fastapi import APIRouter, Request, HTTPException
import stripe
import os

router = APIRouter(prefix="/stripe", tags=["stripe"])

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Price IDs from Stripe Dashboard - UPDATE THESE
PRICE_IDS = {
    "creator": "price_1TC14ZKEElg8TrV5JT5wm0fg",
    "studio": "price_1TC158KEElg8TrV5Noh4aKtf",
}

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


@router.post("/create-checkout-session")
async def create_checkout_session(request: Request):
    """
    Create a Stripe Checkout session.

    Body: { "plan": "creator" | "studio", "user_email": "optional@email.com" }
    """
    try:
        body = await request.json()
        plan = body.get("plan")
        user_email = body.get("user_email")

        if plan not in PRICE_IDS:
            raise HTTPException(status_code=400, detail="Plan invalide")

        session_params = {
            "mode": "subscription",
            "payment_method_types": ["card"],
            "line_items": [{"price": PRICE_IDS[plan], "quantity": 1}],
            "success_url": f"{FRONTEND_URL}/success?session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{FRONTEND_URL}/pricing",
        }

        if user_email:
            session_params["customer_email"] = user_email

        session = stripe.checkout.Session.create(**session_params)
        return {"url": session.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """
    Stripe webhook endpoint.
    Configure it in Stripe Dashboard -> Webhooks.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Handle a few example events
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        customer_email = session.get("customer_email")
        subscription_id = session.get("subscription")
        # TODO: Create/update the user in your DB
        print(f"New subscription: {customer_email} - {subscription_id}")

    elif event["type"] == "customer.subscription.updated":
        subscription = event["data"]["object"]
        # TODO: Update subscription status in your DB
        print(f"Subscription updated: {subscription['id']}")

    elif event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        # TODO: Disable subscription
        print(f"Subscription cancelled: {subscription['id']}")

    return {"status": "ok"}


@router.get("/subscription/{session_id}")
async def get_subscription_details(session_id: str):
    """
    Retrieve subscription details from a Stripe Checkout session id.
    """
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        return {
            "customer_email": session.customer_email,
            "subscription_id": session.subscription,
            "status": session.status,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

