from datetime import datetime, date, time
from typing import List, Optional
from sqlalchemy import String, Integer, Boolean, Time, Date, DateTime, Text, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.database.declarative import Base

class CallLog(Base):
    __tablename__ = "call_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    twilio_call_sid: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    caller_number: Mapped[str] = mapped_column(String(20), nullable=False)
    receiver_number: Mapped[str] = mapped_column(String(20), nullable=False)
    call_status: Mapped[str] = mapped_column(String(50), nullable=False)
    start_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    recording_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    hospital: Mapped["Hospital"] = relationship("Hospital", back_populates="call_logs")
    voice_sessions: Mapped[List["VoiceSession"]] = relationship("VoiceSession", back_populates="call_log", cascade="all, delete-orphan")

class VoiceSession(Base):
    __tablename__ = "voice_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    call_log_id: Mapped[str] = mapped_column(ForeignKey("call_logs.id", ondelete="CASCADE"), nullable=False)
    patient_id: Mapped[Optional[str]] = mapped_column(ForeignKey("patients.id", ondelete="SET NULL"), nullable=True)
    gemini_session_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    session_status: Mapped[str] = mapped_column(String(50), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    call_log: Mapped["CallLog"] = relationship("CallLog", back_populates="voice_sessions")
    patient: Mapped[Optional["Patient"]] = relationship("Patient")
    conversation_logs: Mapped[List["ConversationLog"]] = relationship("ConversationLog", back_populates="voice_session", cascade="all, delete-orphan")
    memory: Mapped[List["ConversationMemory"]] = relationship("ConversationMemory", back_populates="voice_session", cascade="all, delete-orphan")
    tool_logs: Mapped[List["ToolExecutionLog"]] = relationship("ToolExecutionLog", back_populates="voice_session", cascade="all, delete-orphan")

class ConversationLog(Base):
    __tablename__ = "conversation_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    voice_session_id: Mapped[str] = mapped_column(ForeignKey("voice_sessions.id", ondelete="CASCADE"), nullable=False)
    speaker: Mapped[str] = mapped_column(String(50), nullable=False)  # CALLER, AI_RECEPTIONIST
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    voice_session: Mapped["VoiceSession"] = relationship("VoiceSession", back_populates="conversation_logs")

class ConversationMemory(Base):
    __tablename__ = "conversation_memory"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    voice_session_id: Mapped[str] = mapped_column(ForeignKey("voice_sessions.id", ondelete="CASCADE"), nullable=False)
    memory_type: Mapped[str] = mapped_column(String(50), nullable=False)  # SUMMARY, EXTRACTED_ENTITIES, INSIGHT
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    voice_session: Mapped["VoiceSession"] = relationship("VoiceSession", back_populates="memory")

class ToolExecutionLog(Base):
    __tablename__ = "tool_execution_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    voice_session_id: Mapped[str] = mapped_column(ForeignKey("voice_sessions.id", ondelete="CASCADE"), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    arguments: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    execution_status: Mapped[str] = mapped_column(String(50), nullable=False)  # SUCCESS, FAILED
    execution_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    voice_session: Mapped["VoiceSession"] = relationship("VoiceSession", back_populates="tool_logs")

class DoctorAvailabilityCache(Base):
    __tablename__ = "doctor_availability_cache"
    __table_args__ = (UniqueConstraint("doctor_id", "available_date", "slot_start_time", name="uq_doc_slot"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    doctor_id: Mapped[str] = mapped_column(ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False)
    available_date: Mapped[date] = mapped_column(Date, nullable=False)
    slot_start_time: Mapped[time] = mapped_column(Time, nullable=False)
    slot_end_time: Mapped[time] = mapped_column(Time, nullable=False)
    is_booked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    doctor: Mapped["Doctor"] = relationship("Doctor")

class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    hospital: Mapped["Hospital"] = relationship("Hospital")

class FAQ(Base):
    __tablename__ = "faqs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    hospital: Mapped["Hospital"] = relationship("Hospital")
