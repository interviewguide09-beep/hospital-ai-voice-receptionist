from app.database.declarative import Base

# Import all models to register their metadata on Base.metadata
# This is crucial for Alembic autogenerate to discover schema changes
from app.database.models.appointment import (
    Hospital,
    HospitalSetting,
    WorkingHour,
    Department,
    Doctor,
    DoctorSpecialization,
    DoctorSchedule,
    DoctorLeave,
    HospitalHoliday,
    InsuranceProvider,
    Patient,
    Appointment,
    AppointmentStatusHistory
)

from app.database.models.conversation import (
    CallLog,
    VoiceSession,
    ConversationLog,
    ConversationMemory,
    ToolExecutionLog,
    DoctorAvailabilityCache,
    KnowledgeBase,
    FAQ
)

from app.database.models.call_log import (
    PaymentLink,
    Payment,
    Notification,
    NotificationLog,
    User,
    Role,
    Permission,
    RolePermission,
    UserRole,
    AuditLog
)
