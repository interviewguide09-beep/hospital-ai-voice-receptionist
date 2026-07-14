"""
WhatsApp Intake Service
========================
Payment confirm hone ke baad patient ko WhatsApp pe AI conversation start hoti hai.
AI ek-ek sawaal karke medical history collect karti hai aur DB mein save karti hai.

Flow:
  1. Payment verified → start_intake_conversation() call hota hai
  2. Patient ko pehla WhatsApp message jaata hai
  3. Patient reply karta hai → Twilio webhook → handle_patient_reply() call hota hai
  4. Gemini AI decide karta hai: next question bhejo ya data save karo
  5. Sab done → patient ko confirmation message

Session store: In-memory dict (per process). Production mein Redis use kar sakte hain.
Session TTL: 30 minutes
"""

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any

import google.generativeai as genai
from twilio.rest import Client

from app.core.config import settings
from app.core.logging import logger

# ── Thread pool for Twilio blocking calls ──────────────────────────────────
_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="wa_intake")

# ── In-memory session store ────────────────────────────────────────────────
# Structure: { "whatsapp:+91XXXXXXXXXX": { "appointment_id": ..., "stage": ..., "data": {...}, "ts": float } }
_sessions: Dict[str, Dict[str, Any]] = {}
SESSION_TTL = 30 * 60  # 30 minutes

STAGES = [
    "GREETING",          # First message sent, waiting for consent
    "PREV_VISIT",        # Pehle kahi dikhaya?
    "PREV_DOCTOR",       # Kahan dikhaya? (only if yes)
    "REPORTS",           # Report hai?
    "REPORT_DETAILS",    # Kya report? (only if yes)
    "MEDICINES",         # Koi dawai chal rahi?
    "MEDICINE_DETAILS",  # Kya dawai? (only if yes)
    "DONE",              # All collected, save karo
]


def _cleanup_stale_sessions():
    """Remove sessions older than TTL."""
    now = time.time()
    stale = [k for k, v in _sessions.items() if now - v.get("ts", 0) > SESSION_TTL]
    for k in stale:
        del _sessions[k]


def get_session(phone: str) -> Optional[Dict]:
    _cleanup_stale_sessions()
    s = _sessions.get(phone)
    if s and (time.time() - s.get("ts", 0)) < SESSION_TTL:
        return s
    return None


def set_session(phone: str, data: Dict):
    data["ts"] = time.time()
    _sessions[phone] = data


def clear_session(phone: str):
    _sessions.pop(phone, None)


class WhatsAppIntakeService:
    """Manages multi-turn WhatsApp intake conversation with patient using Gemini AI."""

    def __init__(self):
        self.twilio = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        self.from_number = settings.TWILIO_WHATSAPP_FROM
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.model = genai.GenerativeModel("gemini-1.5-flash-latest")

    def _send_sync(self, to: str, body: str) -> Optional[str]:
        """Synchronous Twilio send (runs in thread pool)."""
        try:
            msg = self.twilio.messages.create(
                from_=self.from_number,
                to=to,
                body=body
            )
            logger.info(f"WhatsApp intake sent to {to}. SID: {msg.sid}")
            return msg.sid
        except Exception as e:
            logger.error(f"WhatsApp intake send failed to {to}: {str(e)}")
            return None

    async def _send(self, to: str, body: str):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(_executor, self._send_sync, to, body)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 1: Start conversation after payment
    # ─────────────────────────────────────────────────────────────────────────
    async def start_intake_conversation(
        self,
        appointment_id: str,
        patient_name: str,
        patient_phone: str,
        doctor_name: str,
        appointment_datetime: str
    ):
        """Send first WhatsApp message and create session."""
        # Ensure whatsapp: prefix
        if not patient_phone.startswith("whatsapp:"):
            wa_to = f"whatsapp:{patient_phone}"
        else:
            wa_to = patient_phone

        # Create session
        set_session(wa_to, {
            "appointment_id": appointment_id,
            "patient_name": patient_name,
            "doctor_name": doctor_name,
            "appointment_datetime": appointment_datetime,
            "stage": "GREETING",
            "data": {
                "has_visited_before": None,
                "previous_doctor": None,
                "has_reports": None,
                "report_details": None,
                "current_medicines": None,
                "additional_notes": None,
            },
            "history": []  # Gemini conversation history
        })

        greeting_msg = (
            f"🏥 *CP Tiwari Hospital*\n"
            f"✅ *आपकी अपॉइंटमेंट Confirm हो गई!*\n\n"
            f"नमस्ते *{patient_name}* जी!\n"
            f"👨‍⚕️ Doctor: *{doctor_name}*\n"
            f"📅 समय: *{self._fmt_dt(appointment_datetime)}*\n\n"
            f"Doctor से मिलने से पहले हम कुछ जानकारी लेना चाहते हैं ताकि आपको बेहतर care मिले।\n\n"
            f"क्या आपने पहले इस समस्या के लिए किसी Doctor को दिखाया है?\n"
            f"➡️ *हाँ* या *नहीं* में जवाब दें।"
        )

        await self._send(wa_to, greeting_msg)
        logger.info(f"Intake conversation started for {patient_phone}, appt: {appointment_id}")

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 2: Handle each patient reply
    # ─────────────────────────────────────────────────────────────────────────
    async def handle_patient_reply(self, from_number: str, message_body: str) -> bool:
        """
        Process patient's WhatsApp reply.
        Returns True if handled (is an active intake session), False otherwise.
        """
        session = get_session(from_number)
        if not session:
            return False  # No active session for this number

        stage = session["stage"]
        data = session["data"]
        reply = message_body.strip()

        # Use Gemini to understand intent (haan/nahi/custom text)
        intent = await self._parse_intent(reply)  # "yes" / "no" / "text:<content>"

        next_stage, next_msg = await self._process_stage(stage, intent, reply, session)

        # Update session
        session["stage"] = next_stage
        session["data"] = data
        session["history"].append({"role": "user", "content": reply})
        session["history"].append({"role": "model", "content": next_msg})
        set_session(from_number, session)

        if next_stage == "DONE":
            # Save to DB and clear session
            await self._save_intake(session, from_number)
            await self._send(from_number, next_msg)
            clear_session(from_number)
        else:
            await self._send(from_number, next_msg)

        return True

    # ─────────────────────────────────────────────────────────────────────────
    # Stage machine — decides next question based on current stage + answer
    # ─────────────────────────────────────────────────────────────────────────
    async def _process_stage(self, stage: str, intent: str, raw_reply: str, session: dict):
        data = session["data"]

        if stage == "GREETING":
            # Patient answered: have you seen a doctor before?
            if intent == "yes":
                data["has_visited_before"] = True
                return "PREV_DOCTOR", (
                    "ठीक है! आपने पहले किस Doctor या Hospital में दिखाया था?\n"
                    "कृपया Doctor का नाम या Hospital का नाम बताएं।"
                )
            else:
                data["has_visited_before"] = False
                return "REPORTS", (
                    "समझ गए!\n\n"
                    "क्या आपके पास कोई पुरानी जाँच Report है?\n"
                    "जैसे Blood Report, X-Ray, MRI, ECG वगैरह?\n"
                    "➡️ *हाँ* या *नहीं* में जवाब दें।"
                )

        elif stage == "PREV_DOCTOR":
            data["previous_doctor"] = raw_reply
            return "REPORTS", (
                "धन्यवाद!\n\n"
                "क्या आपके पास कोई पुरानी जाँच Report है?\n"
                "जैसे Blood Report, X-Ray, MRI, ECG वगैरह?\n"
                "➡️ *हाँ* या *नहीं* में जवाब दें।"
            )

        elif stage == "REPORTS":
            if intent == "yes":
                data["has_reports"] = True
                return "REPORT_DETAILS", (
                    "अच्छा! कौन सी Report है आपके पास?\n"
                    "जैसे: *Blood Report, X-Ray, MRI, ECG* — जो हो वो बताएं।\n"
                    "Report लेकर आना बिल्कुल मत भूलें! 📋"
                )
            else:
                data["has_reports"] = False
                return "MEDICINES", (
                    "ठीक है!\n\n"
                    "क्या आप अभी कोई दवाई ले रहे हैं?\n"
                    "➡️ *हाँ* या *नहीं* में जवाब दें।"
                )

        elif stage == "REPORT_DETAILS":
            data["report_details"] = raw_reply
            return "MEDICINES", (
                "Perfect! Report ज़रूर साथ लाएं।\n\n"
                "क्या आप अभी कोई दवाई ले रहे हैं?\n"
                "➡️ *हाँ* या *नहीं* में जवाब दें।"
            )

        elif stage == "MEDICINES":
            if intent == "yes":
                data["current_medicines"] = True  # temp flag
                return "MEDICINE_DETAILS", (
                    "कौन सी दवाई ले रहे हैं?\n"
                    "दवाई का नाम बताएं — अगर याद न हो तो photo भी WhatsApp कर सकते हैं।"
                )
            else:
                data["current_medicines"] = None
                return "DONE", self._build_done_message(data, session)

        elif stage == "MEDICINE_DETAILS":
            data["current_medicines"] = raw_reply
            return "DONE", self._build_done_message(data, session)

        else:
            return "DONE", self._build_done_message(data, session)

    def _build_done_message(self, data: dict, session: dict) -> str:
        return (
            f"✅ *बहुत बढ़िया {session['patient_name']} जी!*\n\n"
            f"आपकी सारी जानकारी Doctor के पास पहुँच गई है।\n"
            f"Doctor साहब आपसे मिलने पर इसे देखेंगे।\n\n"
            f"📅 समय पर आइएगा:\n*{self._fmt_dt(session['appointment_datetime'])}*\n\n"
            f"किसी भी सहायता के लिए call करें। धन्यवाद! 🙏\n"
            f"_— CP Tiwari Hospital_"
        )

    async def _parse_intent(self, reply: str) -> str:
        """Use Gemini to classify reply as yes/no/text."""
        lower = reply.lower().strip()
        # Fast local check first
        yes_words = {"हाँ", "हा", "han", "yes", "haan", "y", "ha", "bilkul", "bilkul ha", "ok", "okay", "theek hai", "ठीक है", "हाँ जी", "हां"}
        no_words = {"नहीं", "nahi", "no", "nhi", "nahin", "n", "नही", "नहीं जी"}
        if lower in yes_words:
            return "yes"
        if lower in no_words:
            return "no"
        # Partial match
        for w in yes_words:
            if w in lower:
                return "yes"
        for w in no_words:
            if w in lower:
                return "no"
        return f"text:{reply}"

    async def _save_intake(self, session: dict, from_number: str):
        """Save collected intake data to patient_intakes table."""
        try:
            from app.database.session import async_session_factory
            from app.database.models.appointment import PatientIntake
            from sqlalchemy import select
            import uuid

            data = session["data"]
            appointment_id = session["appointment_id"]

            async with async_session_factory() as db:
                # Check if intake already exists
                existing = (await db.execute(
                    select(PatientIntake).where(PatientIntake.appointment_id == appointment_id)
                )).scalar_one_or_none()

                raw_transcript = json.dumps(session.get("history", []), ensure_ascii=False)

                if existing:
                    existing.has_visited_before = data.get("has_visited_before")
                    existing.previous_doctor = data.get("previous_doctor")
                    existing.has_reports = data.get("has_reports")
                    existing.report_details = data.get("report_details")
                    existing.current_medicines = data.get("current_medicines") if isinstance(data.get("current_medicines"), str) else None
                    existing.additional_notes = data.get("additional_notes")
                    existing.raw_transcript = raw_transcript
                else:
                    intake = PatientIntake(
                        id=str(uuid.uuid4()),
                        appointment_id=appointment_id,
                        has_visited_before=data.get("has_visited_before"),
                        previous_doctor=data.get("previous_doctor"),
                        has_reports=data.get("has_reports"),
                        report_details=data.get("report_details"),
                        current_medicines=data.get("current_medicines") if isinstance(data.get("current_medicines"), str) else None,
                        additional_notes=data.get("additional_notes"),
                        raw_transcript=raw_transcript
                    )
                    db.add(intake)

                await db.commit()
                logger.info(f"WhatsApp intake saved for appointment: {appointment_id}")

        except Exception as e:
            logger.error(f"Failed to save WhatsApp intake: {str(e)}", exc_info=True)

    def _fmt_dt(self, dt_str: str) -> str:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(dt_str)
            return dt.strftime("%d %b %Y, %I:%M %p")
        except Exception:
            return dt_str or "N/A"


# Singleton instance
_intake_service: Optional[WhatsAppIntakeService] = None

def get_intake_service() -> WhatsAppIntakeService:
    global _intake_service
    if _intake_service is None:
        _intake_service = WhatsAppIntakeService()
    return _intake_service
