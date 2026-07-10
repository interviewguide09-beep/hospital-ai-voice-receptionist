"""
WhatsApp Notification Service — Twilio WhatsApp API se directly notification bhejo.
n8n ki zarurat nahi. Twilio ke same credentials use karta hai jo voice ke liye hain.

Do types ke messages:
  1. Receptionist ko — nai appointment ki table notification
  2. Patient ko — unki appointment confirmation + payment link

Setup:
------
TESTING (Sandbox):
  1. https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn par jao
  2. WhatsApp se +14155238886 par "join <sandbox-word>" bhejo
  3. .env mein TWILIO_WHATSAPP_FROM=whatsapp:+14155238886 rakho

PRODUCTION:
  1. Twilio Console mein WhatsApp Business number approve karwao
  2. .env mein TWILIO_WHATSAPP_FROM=whatsapp:+91XXXXXXXXXX update karo
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional
from twilio.rest import Client
from app.core.config import settings
from app.core.logging import logger

# Thread pool for running synchronous Twilio calls without blocking async event loop
_whatsapp_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="whatsapp")


class WhatsAppNotificationService:
    """Sends WhatsApp messages via Twilio WhatsApp API directly from Python code."""

    def __init__(self):
        self.client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        self.from_number = settings.TWILIO_WHATSAPP_FROM
        self.receptionist_number = settings.RECEPTIONIST_WHATSAPP_NUMBER

    def _is_configured(self) -> bool:
        """Check if WhatsApp notification is configured."""
        return bool(self.receptionist_number and self.receptionist_number != "whatsapp:+919999999999")

    def _send_sync(self, to: str, body: str) -> Optional[str]:
        """Synchronous Twilio API call — runs inside thread pool."""
        try:
            message = self.client.messages.create(
                from_=self.from_number,
                to=to,
                body=body
            )
            logger.info(f"SUCCESS: WhatsApp sent to {to}. SID: {message.sid}")
            return message.sid
        except Exception as e:
            logger.error(f"ERROR: WhatsApp send failed to {to}: {str(e)}")
            return None

    def _format_datetime(self, dt_str: str) -> str:
        """Convert ISO datetime string to human-readable Hindi-friendly format."""
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(dt_str)
            return dt.strftime("%d %b %Y, %I:%M %p")
        except Exception:
            return dt_str or "N/A"

    async def send_appointment_booked(self, details: dict) -> None:
        """
        Nayi appointment book hone par RECEPTIONIST ke WhatsApp par notification bhejo.
        Non-blocking — event loop ko block nahi karta.
        """
        if not self._is_configured():
            logger.warning(
                "WhatsApp notification skipped: RECEPTIONIST_WHATSAPP_NUMBER not set in .env."
            )
            return

        appt_display = self._format_datetime(details.get("appointment_datetime", ""))

        message_body = (
            f"🏥 *CP Tiwari Hospital*\n"
            f"📋 *नई अपॉइंटमेंट बुक हुई!*\n\n"
            f"👤 *मरीज़:* {details.get('patient_name', 'N/A')}\n"
            f"📞 *मोबाइल:* {details.get('patient_phone', 'N/A')}\n"
            f"👨‍⚕️ *डॉक्टर:* {details.get('doctor_name', 'N/A')}\n"
            f"📅 *समय:* {appt_display}\n"
            f"🩺 *समस्या:* {details.get('reason', 'N/A')}\n"
            f"🆔 *ID:* ...{details.get('appointment_id', 'N/A')[-8:]}\n\n"
            f"📊 _आज का Schedule:_ {settings.TWILIO_WEBHOOK_URL}receptionist/schedule"
        )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            _whatsapp_executor,
            self._send_sync,
            self.receptionist_number,
            message_body
        )

    async def send_patient_confirmation(self, details: dict) -> None:
        """
        Appointment confirm hone par PATIENT ke apne WhatsApp number par
        sari details + payment link bhejo.
        """
        patient_phone_raw = details.get("patient_phone", "")
        if not patient_phone_raw:
            logger.warning("Patient WhatsApp skipped: patient_phone not available.")
            return

        # Ensure whatsapp: prefix
        if not patient_phone_raw.startswith("whatsapp:"):
            patient_to = f"whatsapp:{patient_phone_raw}"
        else:
            patient_to = patient_phone_raw

        appt_display = self._format_datetime(details.get("appointment_datetime", ""))
        
        # Dynamically build payment checkout URL using public ngrok / webhook URL if available
        base_url = settings.TWILIO_WEBHOOK_URL.rstrip('/') if settings.TWILIO_WEBHOOK_URL else settings.PAYMENT_BASE_URL.rstrip('/')
        payment_link = f"{base_url}/payment/checkout"
        appt_id_short = details.get('appointment_id', 'N/A')[-8:]

        message_body = (
            f"🏥 *CP Tiwari Hospital*\n"
            f"✅ *आपकी अपॉइंटमेंट बुक हो गई!*\n\n"
            f"👤 *नाम:* {details.get('patient_name', 'N/A')}\n"
            f"👨‍⚕️ *डॉक्टर:* {details.get('doctor_name', 'N/A')}\n"
            f"📅 *तारीख व समय:* {appt_display}\n"
            f"🩺 *समस्या:* {details.get('reason', 'N/A')}\n"
            f"🆔 *Appointment ID:* {appt_id_short}\n\n"
            f"💳 *Payment करें और अपॉइंटमेंट Confirm करें:*\n"
            f"{payment_link}?appt={appt_id_short}\n\n"
            f"_Payment के बाद आपकी अपॉइंटमेंट confirmed हो जाएगी।_\n"
            f"_किसी सहायता के लिए हमें call करें।_"
        )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            _whatsapp_executor,
            self._send_sync,
            patient_to,
            message_body
        )

    async def send_payment_confirmation(self, details: dict) -> None:
        """
        Send a payment success and final appointment confirmation WhatsApp message to the patient.
        """
        patient_phone_raw = details.get("patient_phone", "")
        if not patient_phone_raw:
            logger.warning("Patient WhatsApp skipped: patient_phone not available.")
            return

        # Ensure whatsapp: prefix
        if not patient_phone_raw.startswith("whatsapp:"):
            patient_to = f"whatsapp:{patient_phone_raw}"
        else:
            patient_to = patient_phone_raw

        appt_display = self._format_datetime(details.get("appointment_datetime", ""))
        appt_id_short = details.get('appointment_id', 'N/A')[-8:]

        message_body = (
            f"🏥 *CP Tiwari Hospital*\n"
            f"🎉 *पेमेंट प्राप्त हुआ - अपॉइंटमेंट पक्की हो गई!*\n\n"
            f"नमस्ते {details.get('patient_name', 'N/A')} जी,\n"
            f"हमें आपका पेमेंट सफलतापूर्वक प्राप्त हो गया है।\n\n"
            f"👤 *मरीज़:* {details.get('patient_name', 'N/A')}\n"
            f"👨‍⚕️ *डॉक्टर:* {details.get('doctor_name', 'N/A')}\n"
            f"📅 *तारीख व समय:* {appt_display}\n"
            f"🩺 *समस्या:* {details.get('reason', 'N/A')}\n"
            f"🆔 *Appointment ID:* {appt_id_short}\n\n"
            f"✅ *आपकी अपॉइंटमेंट अब confirmed है।* आपको अस्पताल पहुंचने पर सीधे ओपीडी (OPD) में प्रवेश मिलेगा।\n\n"
            f"_CP Tiwari Hospital पर विश्वास जताने के लिए धन्यवाद!_"
        )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            _whatsapp_executor,
            self._send_sync,
            patient_to,
            message_body
        )

    async def send_daily_summary(self, hospital_id: str = "hosp_default") -> None:
        """
        Subah ek baar aaj ka poora schedule WhatsApp par bhejo.
        Isko scheduler se call kar sakte ho ya cron job se.
        """
        if not self._is_configured():
            return

        try:
            from datetime import date, datetime
            from sqlalchemy import select, and_
            from app.database.session import async_session_factory
            from app.database.models.appointment import Appointment, Patient, Doctor

            today = date.today()
            today_display = today.strftime("%d %B %Y, %A")

            async with async_session_factory() as db:
                start_dt = datetime.combine(today, datetime.min.time())
                end_dt = datetime.combine(today, datetime.max.time())

                stmt = (
                    select(Appointment, Patient, Doctor)
                    .join(Patient, Appointment.patient_id == Patient.id)
                    .join(Doctor, Appointment.doctor_id == Doctor.id)
                    .where(
                        and_(
                            Appointment.hospital_id == hospital_id,
                            Appointment.appointment_datetime >= start_dt,
                            Appointment.appointment_datetime <= end_dt,
                            Appointment.status.in_(["SCHEDULED", "PENDING_PAYMENT"])
                        )
                    )
                    .order_by(Doctor.first_name, Appointment.appointment_datetime)
                )
                results = (await db.execute(stmt)).all()

            if not results:
                message_body = (
                    f"🏥 *CP Tiwari Hospital*\n"
                    f"📅 *आज का Schedule — {today_display}*\n\n"
                    f"आज कोई अपॉइंटमेंट नहीं है।"
                )
            else:
                lines = [
                    f"🏥 *CP Tiwari Hospital*",
                    f"📅 *आज का Schedule — {today_display}*",
                    f"कुल अपॉइंटमेंट: *{len(results)}*\n",
                ]
                current_doc = None
                for appt, patient, doctor in results:
                    doc_name = f"Dr. {doctor.first_name} {doctor.last_name}"
                    if doc_name != current_doc:
                        lines.append(f"\n👨‍⚕️ *{doc_name}*")
                        current_doc = doc_name
                    time_str = appt.appointment_datetime.strftime("%I:%M %p")
                    patient_name = f"{patient.first_name} {patient.last_name}".strip()
                    lines.append(f"  • {time_str} — {patient_name} ({patient.phone})")

                message_body = "\n".join(lines)

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                _whatsapp_executor,
                self._send_sync,
                self.receptionist_number,
                message_body
            )

        except Exception as e:
            logger.error(f"WhatsApp daily summary failed: {str(e)}")
