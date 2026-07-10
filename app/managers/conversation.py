import uuid
from typing import Dict, Any, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models.conversation import VoiceSession, CallLog
from app.services.gemini_service import GeminiService
from app.services.twilio_service import TwilioService
from app.engines.decision import DecisionEngine
from app.engines.scheduling import SchedulingEngine
from app.engines.appointment import AppointmentEngine
from app.engines.memory import MemoryEngine
from app.managers.prompt import PromptManager
from app.core.exceptions import OutOfScopeException, BaseAppException
from app.core.logging import logger

EMERGENCY_WORDS = ["chest pain", "heart attack", "choking", "stop breathing", "not breathing", "bleeding heavily", "stroke", "seizure", "unconscious"]

class ConversationManager:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.gemini = GeminiService()
        self.twilio = TwilioService()
        self.decision = DecisionEngine(self.gemini)
        self.scheduling = SchedulingEngine(db_session)
        self.appointment = AppointmentEngine(db_session)
        self.memory = MemoryEngine(db_session, self.gemini)
        self.prompt_manager = PromptManager(db_session)

    async def process_turn(self, voice_session_id: str, user_utterance: str) -> Dict[str, Any]:
        """Orchestrates the speech-to-text pipeline process, screening inputs, resolving intent, executing db tools, and returning speech text."""
        logger.info(f"Processing turn for session {voice_session_id}. Input: '{user_utterance}'")
        
        # 1. Fetch Voice Session
        session_stmt = select(VoiceSession).where(VoiceSession.id == voice_session_id)
        session = (await self.db.execute(session_stmt)).scalar_one_or_none()
        if not session:
            logger.error(f"Voice session {voice_session_id} not found in database.")
            return {
                "action": "HANGUP",
                "speech_response": "I apologize, but your session could not be verified. Goodbye."
            }

        # 2. Fetch Hospital ID from Call Log
        call_stmt = select(CallLog).where(CallLog.id == session.call_log_id)
        call_log = (await self.db.execute(call_stmt)).scalar_one_or_none()
        hospital_id = call_log.hospital_id if call_log else "hosp_default"

        # 3. Emergency Triage Screening (Priority 1)
        normalized_utterance = user_utterance.lower()
        if any(word in normalized_utterance for word in EMERGENCY_WORDS):
            logger.warning(f"Emergency indicators matched in session {voice_session_id}!")
            return {
                "action": "TRANSFER",
                "transfer_number": "+1911",
                "speech_response": "You are indicating a medical emergency. Please hang up and dial nine one one immediately, or hold while I transfer your call."
            }

        # 4. Save User Utterance to Logs
        await self.memory.log_turn(voice_session_id, "CALLER", user_utterance)

        # 5. Intent and Guardrails Screening (Priority 2)
        running_summary = await self.memory.get_latest_summary(voice_session_id)
        try:
            intent_class = await self.decision.determine_intent(user_utterance, running_summary)
        except OutOfScopeException as exc:
            # Catch out of scope violations and reply with guardrail warning
            await self.memory.log_turn(voice_session_id, "AI_RECEPTIONIST", exc.message)
            return {
                "action": "SPEAK",
                "speech_response": exc.message
            }

        # 6. Check for FAQ queries & compile FAQ context
        faq_context = None
        if intent_class.intent == "GENERAL_FAQ":
            # Search FAQs table for answers
            from app.database.models.conversation import FAQ
            faq_stmt = select(FAQ).where(FAQ.hospital_id == hospital_id)
            faqs = (await self.db.execute(faq_stmt)).scalars().all()
            faq_context = "\n".join([f"Q: {f.question}\nA: {f.answer}" for f in faqs])

        # 7. Compile Prompt
        patient_name = None
        if session.patient:
            patient_name = f"{session.patient.first_name} {session.patient.last_name}"
            
        system_instruction = await self.prompt_manager.compile_receptionist_prompt(
            hospital_id=hospital_id,
            patient_name=patient_name,
            running_summary=running_summary,
            active_faq_context=faq_context
        )

        # 8. Fetch chat history formatted for Gemini
        history = await self.memory.get_session_history(voice_session_id)

        # 9. Call Gemini to generate receptionist speech response
        chat_result = await self.gemini.generate_chat_turn_async(
            history=history,
            system_instruction=system_instruction
        )
        
        speech_response = chat_result["text"].strip()

        # 10. Perform post-generation summaries to manage memory depth
        if len(history) >= 6:
            await self.memory.generate_running_summary(voice_session_id)

        # 11. Save AI Response to Logs
        await self.memory.log_turn(voice_session_id, "AI_RECEPTIONIST", speech_response)

        return {
            "action": "SPEAK",
            "speech_response": speech_response
        }
