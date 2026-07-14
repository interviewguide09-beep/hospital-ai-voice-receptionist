"""
WhatsApp Webhook Endpoint
===========================
Twilio se incoming WhatsApp messages receive karta hai.
Agar message kisi active intake session se match kare → WhatsAppIntakeService handle karta hai.
Baaki messages ko ignore karta hai (ya future mein other bots ke liye extend kar sakte hain).

Twilio Console mein WhatsApp Sandbox webhook set karo:
  URL: https://<your-domain>/whatsapp/webhook
  Method: POST
"""

from fastapi import APIRouter, Form, Response
from app.services.whatsapp_intake import get_intake_service
from app.core.logging import logger

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


@router.post("/webhook")
async def whatsapp_incoming_webhook(
    From: str = Form(...),          # e.g. "whatsapp:+91XXXXXXXXXX"
    Body: str = Form(...),          # Patient ka message
    MessageSid: str = Form(None),   # Twilio Message SID
    To: str = Form(None),           # Our WhatsApp number
):
    """
    Twilio WhatsApp incoming message webhook.
    Handles patient replies during AI intake conversation.
    Returns empty TwiML response (reply is sent via REST API, not TwiML).
    """
    logger.info(f"WhatsApp incoming from {From}: '{Body[:80]}' (SID: {MessageSid})")

    try:
        intake_service = get_intake_service()
        handled = await intake_service.handle_patient_reply(From, Body)

        if not handled:
            logger.debug(f"WhatsApp message from {From} had no active intake session — ignored.")

    except Exception as e:
        logger.error(f"WhatsApp webhook handler error: {str(e)}", exc_info=True)

    # Always return empty 200 OK to Twilio (to prevent retries)
    return Response(content="", media_type="text/xml", status_code=200)
