import uuid
from typing import List, Dict, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models.conversation import ConversationLog, ConversationMemory
from app.services.gemini_service import GeminiService
from app.core.logging import engine_logger

class MemoryEngine:
    def __init__(self, db_session: AsyncSession, gemini_service: Optional[GeminiService] = None):
        self.db = db_session
        self.gemini = gemini_service

    async def log_turn(self, voice_session_id: str, speaker: str, transcript: str, confidence_score: Optional[float] = None) -> None:
        """Saves a single dialogue turn (caller or AI receptionist speech) to the database."""
        engine_logger.debug(f"Logging turn for session {voice_session_id}: {speaker}: '{transcript[:30]}...'")
        log = ConversationLog(
            id=str(uuid.uuid4()),
            voice_session_id=voice_session_id,
            speaker=speaker,
            transcript=transcript,
            confidence_score=confidence_score
        )
        self.db.add(log)
        await self.db.flush()

    async def get_session_history(self, voice_session_id: str) -> List[Dict[str, str]]:
        """Retrieves raw conversation logs from the database, formatted for Gemini Chat API consumption."""
        stmt = select(ConversationLog).where(ConversationLog.voice_session_id == voice_session_id).order_by(ConversationLog.created_at.asc())
        logs = (await self.db.execute(stmt)).scalars().all()
        
        # Map DB speaker names (CALLER, AI_RECEPTIONIST) to Gemini roles (user, model)
        history = []
        for log in logs:
            role = "user" if log.speaker == "CALLER" else "model"
            history.append({"role": role, "content": log.transcript})
        return history

    async def generate_running_summary(self, voice_session_id: str) -> str:
        """Summarizes dialogue history to date using Gemini, saving the output in context memory."""
        engine_logger.info(f"Generating running summary for session {voice_session_id}")
        
        if not self.gemini:
            engine_logger.warning("GeminiService not injected into MemoryEngine. Skipping summary generation.")
            return ""

        # Fetch recent logs
        history = await self.get_session_history(voice_session_id)
        if not history:
            return "No conversation history exists yet."

        history_str = "\n".join([f"{turn['role'].upper()}: {turn['content']}" for turn in history])
        
        prompt = (
            "Summarize the following phone call conversation between a caller and a Hospital AI Receptionist. "
            "Focus on the patient's concern, the doctor requested, the department, and any appointment details "
            "established so far. Keep it under 3 sentences:\n\n"
            f"{history_str}"
        )

        system_instruction = "You are a concise medical receptionist summarizing phone call logs."
        
        try:
            # Generate summary text
            summary_dict = await self.gemini.generate_chat_turn_async(
                history=[{"role": "user", "content": prompt}],
                system_instruction=system_instruction
            )
            summary_text = summary_dict["text"].strip()
            
            # Save to Memory database table
            mem = ConversationMemory(
                id=str(uuid.uuid4()),
                voice_session_id=voice_session_id,
                memory_type="SUMMARY",
                content=summary_text
            )
            self.db.add(mem)
            await self.db.flush()
            
            engine_logger.info(f"Running summary created: '{summary_text}'")
            return summary_text
        except Exception as e:
            engine_logger.error(f"Failed to generate and save conversational running summary: {str(e)}")
            return ""

    async def get_latest_summary(self, voice_session_id: str) -> Optional[str]:
        """Retrieves the latest running summary stored in the database for the active call session."""
        stmt = (
            select(ConversationMemory)
            .where(
                ConversationMemory.voice_session_id == voice_session_id,
                ConversationMemory.memory_type == "SUMMARY"
            )
            .order_by(ConversationMemory.created_at.desc())
            .limit(1)
        )
        mem = (await self.db.execute(stmt)).scalar_one_or_none()
        return mem.content if mem else None
