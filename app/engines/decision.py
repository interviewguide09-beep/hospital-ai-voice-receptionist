from typing import Optional
from pydantic import BaseModel, Field
from app.services.gemini_service import GeminiService
from app.core.logging import engine_logger
from app.core.exceptions import OutOfScopeException

class IntentClassification(BaseModel):
    intent: str = Field(
        ...,
        description="Intent of the caller. Must be one of: BOOK_APPOINTMENT, CANCEL_APPOINTMENT, INQUIRE_DEPARTMENT, GENERAL_FAQ, EMERGENCY, OUT_OF_SCOPE"
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason: str = Field(..., description="Explanation of why this intent was selected.")
    out_of_scope_category: Optional[str] = Field(
        None,
        description="If out of scope, category: POLITICS, PROGRAMMING, JOKES, MEDICAL_DIAGNOSIS, MEDICINE_PRESCRIPTION, OTHER"
    )

class DecisionEngine:
    def __init__(self, gemini_service: GeminiService):
        self.gemini = gemini_service

    async def determine_intent(self, user_utterance: str, history_summary: Optional[str] = None) -> IntentClassification:
        """Determines the caller's intent and evaluates guardrail categories using Gemini."""
        engine_logger.info(f"Analyzing intent for input: '{user_utterance[:40]}...'")

        system_instruction = (
            "You are the classification component of a professional Hospital AI Voice Receptionist. "
            "Your job is to identify the user's intent. "
            "Strictly enforce safety guardrails: "
            "- Under NO circumstances allow jokes, politics, programming questions, medical diagnosis, or medicine prescribing. "
            "- If the user asks for diagnosis, treatment, or medications, classify as OUT_OF_SCOPE and set category to MEDICAL_DIAGNOSIS or MEDICINE_PRESCRIPTION. "
            "- If the user asks for programming code, algorithms, or political opinions, classify as OUT_OF_SCOPE and set category appropriately."
        )

        prompt = (
            f"User Utterance: {user_utterance}\n"
            f"Recent Context Summary: {history_summary or 'None'}\n"
            "Classify the intent precisely using the schema."
        )

        classification: IntentClassification = await self.gemini.generate_structured_output_async(
            prompt=prompt,
            response_schema=IntentClassification,
            system_instruction=system_instruction
        )

        engine_logger.info(f"Intent classified: {classification.intent} (Confidence: {classification.confidence})")

        # Raise out of scope exception if flagged by guardrails
        if classification.intent == "OUT_OF_SCOPE":
            engine_logger.warning(f"Guardrail triggered. Category: {classification.out_of_scope_category}")
            if classification.out_of_scope_category in ("MEDICAL_DIAGNOSIS", "MEDICINE_PRESCRIPTION"):
                raise OutOfScopeException("I apologize, but as a receptionist, I am not permitted to diagnose symptoms, recommend treatments, or prescribe medications. Please consult a qualified doctor or visit our clinic for medical advice.")
            elif classification.out_of_scope_category == "PROGRAMMING":
                raise OutOfScopeException("I cannot assist with programming, software development, or coding tasks. I can only assist with hospital services and scheduling.")
            elif classification.out_of_scope_category == "POLITICS":
                raise OutOfScopeException("I cannot discuss politics or current political affairs. I can only assist you with hospital operations and scheduling.")
            elif classification.out_of_scope_category == "JOKES":
                raise OutOfScopeException("I am here to assist with professional hospital scheduling and inquiries, so I cannot tell jokes.")
            else:
                raise OutOfScopeException("I am only authorized to perform hospital receptionist tasks, such as booking, rescheduling, or canceling appointments.")

        return classification
