# Import all models to register them on SQLAlchemy Base metadata and prevent mapper configuration errors
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
