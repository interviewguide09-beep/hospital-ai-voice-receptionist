import httpx
from typing import Dict, Any
from app.core.config import settings
from app.core.logging import logger
from app.core.exceptions import ThirdPartyException

class AutomationService:
    def __init__(self):
        self.webhook_url = settings.N8N_WEBHOOK_URL
        self.api_key = settings.N8N_API_KEY
        self.headers = {
            "Content-Type": "application/json",
            "X-n8n-API-Key": self.api_key
        }

    async def dispatch_appointment_booked_webhook(self, appointment_details: Dict[str, Any]) -> None:
        """Dispatches structured appointment details to n8n webhook for calendars sync and SMS alerts."""
        logger.info(f"Dispatching appointment booking webhook to n8n for ID: {appointment_details.get('appointment_id')}")
        payload = {
            "event": "appointment.booked",
            "timestamp": datetime_to_iso_helper(),
            "data": appointment_details
        }
        await self._send_webhook(payload)

    async def dispatch_payment_received_webhook(self, payment_details: Dict[str, Any]) -> None:
        """Dispatches received copayments details to n8n workflow for invoicing."""
        logger.info(f"Dispatching payment webhook to n8n for Tx: {payment_details.get('transaction_reference')}")
        payload = {
            "event": "payment.received",
            "timestamp": datetime_to_iso_helper(),
            "data": payment_details
        }
        await self._send_webhook(payload)

    async def _send_webhook(self, payload: Dict[str, Any]) -> None:
        """Internal helper handling HTTP POST request execution to the n8n endpoint."""
        if not self.webhook_url:
            logger.warning("n8n webhook URL is not configured. Skipping event dispatch.")
            return

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.webhook_url,
                    json=payload,
                    headers=self.headers,
                    timeout=10.0
                )
                if response.status_code not in (200, 201, 202):
                    logger.error(f"n8n webhook responded with error status: {response.status_code} | Body: {response.text}")
                    raise ThirdPartyException(f"n8n webhook returned status code: {response.status_code}")
                logger.info("Successfully dispatched event payload to n8n.")
            except httpx.RequestError as exc:
                logger.error(f"HTTP request error during n8n dispatch: {str(exc)}")
                raise ThirdPartyException(f"Failed to communicate with n8n workflow runner: {str(exc)}")

def datetime_to_iso_helper() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
