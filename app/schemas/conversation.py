from datetime import datetime, date, time
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict

class CallLogBase(BaseModel):
    twilio_call_sid: str = Field(..., max_length=100)
    caller_number: str = Field(..., max_length=20)
    receiver_number: str = Field(..., max_length=20)
    call_status: str = Field(..., max_length=50)

class CallLogCreate(CallLogBase):
    hospital_id: str

class CallLogRead(CallLogBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    hospital_id: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    recording_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class VoiceSessionBase(BaseModel):
    call_log_id: str
    patient_id: Optional[str] = None
    gemini_session_id: Optional[str] = Field(None, max_length=100)
    session_status: str = "ACTIVE"

class VoiceSessionCreate(VoiceSessionBase):
    pass

class VoiceSessionRead(VoiceSessionBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    updated_at: datetime

class ConversationLogBase(BaseModel):
    voice_session_id: str
    speaker: str = Field(..., max_length=50)  # CALLER, AI_RECEPTIONIST
    transcript: str

class ConversationLogCreate(ConversationLogBase):
    confidence_score: Optional[float] = None

class ConversationLogRead(ConversationLogBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    confidence_score: Optional[float] = None
    created_at: datetime
    updated_at: datetime

class ConversationMemoryCreate(BaseModel):
    voice_session_id: str
    memory_type: str = Field(..., max_length=50)  # SUMMARY, EXTRACTED_ENTITIES, INSIGHT
    content: str

class ConversationMemoryRead(ConversationMemoryCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    updated_at: datetime

class FAQBase(BaseModel):
    question: str
    answer: str
    category: Optional[str] = Field(None, max_length=100)

class FAQCreate(FAQBase):
    hospital_id: str

class FAQRead(FAQBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    hospital_id: str
    is_active: bool
    created_at: datetime

class KnowledgeBaseBase(BaseModel):
    title: str = Field(..., max_length=255)
    content: str
    category: Optional[str] = Field(None, max_length=100)

class KnowledgeBaseCreate(KnowledgeBaseBase):
    hospital_id: str

class KnowledgeBaseRead(KnowledgeBaseBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    hospital_id: str
    is_active: bool
    created_at: datetime

class ToolExecutionLogCreate(BaseModel):
    voice_session_id: str
    tool_name: str = Field(..., max_length=100)
    arguments: str
    response: Optional[str] = None
    execution_status: str = Field(..., max_length=50)
    execution_time_ms: int

class ToolExecutionLogRead(ToolExecutionLogCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
