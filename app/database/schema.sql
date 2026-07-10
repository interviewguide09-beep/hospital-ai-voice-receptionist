-- ==========================================
-- HOSPITAL AI VOICE RECEPTIONIST SCHEMA (MySQL 8.0)
-- Production-Ready, Highly Normalized, Multi-Hospital Architecture
-- ==========================================

CREATE DATABASE IF NOT EXISTS hospital_voice_db;
USE hospital_voice_db;

-- 1. HOSPITALS (Multi-hospital master table)
CREATE TABLE hospitals (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) NOT NULL UNIQUE,
    address TEXT NULL,
    phone VARCHAR(20) NOT NULL UNIQUE,
    email VARCHAR(255) NULL,
    timezone VARCHAR(50) DEFAULT 'UTC' NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    INDEX idx_hospitals_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. HOSPITAL SETTINGS (Key-Value settings per hospital for custom prompt behaviors/gateways)
CREATE TABLE hospital_settings (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    hospital_id VARCHAR(36) NOT NULL,
    setting_key VARCHAR(100) NOT NULL,
    setting_value TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_settings_hospital FOREIGN KEY (hospital_id) REFERENCES hospitals(id) ON DELETE CASCADE,
    UNIQUE KEY uq_hospital_key (hospital_id, setting_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. WORKING HOURS (Weekly operational schedule per hospital)
CREATE TABLE working_hours (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    hospital_id VARCHAR(36) NOT NULL,
    day_of_week TINYINT NOT NULL COMMENT '1=Monday, 7=Sunday',
    open_time TIME NOT NULL,
    close_time TIME NOT NULL,
    is_closed BOOLEAN DEFAULT FALSE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_working_hours_hospital FOREIGN KEY (hospital_id) REFERENCES hospitals(id) ON DELETE CASCADE,
    UNIQUE KEY uq_hospital_day (hospital_id, day_of_week),
    CONSTRAINT chk_day_range CHECK (day_of_week BETWEEN 1 AND 7)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. DEPARTMENTS (Clinical departments under each hospital)
CREATE TABLE departments (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    hospital_id VARCHAR(36) NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT NULL,
    phone_extension VARCHAR(10) NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_departments_hospital FOREIGN KEY (hospital_id) REFERENCES hospitals(id) ON DELETE CASCADE,
    INDEX idx_departments_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5. DOCTORS (Medical practitioners working in departments)
CREATE TABLE doctors (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    hospital_id VARCHAR(36) NOT NULL,
    department_id VARCHAR(36) NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(255) NULL,
    phone VARCHAR(20) NULL,
    license_number VARCHAR(100) NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_doctors_hospital FOREIGN KEY (hospital_id) REFERENCES hospitals(id) ON DELETE CASCADE,
    CONSTRAINT fk_doctors_department FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE RESTRICT,
    INDEX idx_doctors_active (is_active),
    INDEX idx_doctors_name (last_name, first_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6. DOCTOR SPECIALIZATIONS (Doctors' areas of clinical expertise)
CREATE TABLE doctor_specializations (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    doctor_id VARCHAR(36) NOT NULL,
    specialization VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_specializations_doctor FOREIGN KEY (doctor_id) REFERENCES doctors(id) ON DELETE CASCADE,
    INDEX idx_specialization (specialization)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 7. DOCTOR SCHEDULES (Weekly schedule templates for appointments booking)
CREATE TABLE doctor_schedules (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    doctor_id VARCHAR(36) NOT NULL,
    day_of_week TINYINT NOT NULL COMMENT '1=Monday, 7=Sunday',
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    slot_duration_minutes INT DEFAULT 30 NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_schedules_doctor FOREIGN KEY (doctor_id) REFERENCES doctors(id) ON DELETE CASCADE,
    UNIQUE KEY uq_doctor_day_time (doctor_id, day_of_week, start_time),
    CONSTRAINT chk_schedule_day CHECK (day_of_week BETWEEN 1 AND 7)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 8. DOCTOR LEAVES (Planned leaves where scheduling is blocked)
CREATE TABLE doctor_leaves (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    doctor_id VARCHAR(36) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    reason VARCHAR(255) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_leaves_doctor FOREIGN KEY (doctor_id) REFERENCES doctors(id) ON DELETE CASCADE,
    INDEX idx_leaves_dates (start_date, end_date),
    CONSTRAINT chk_leave_dates CHECK (end_date >= start_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 9. HOSPITAL HOLIDAYS (Public holidays blocking all regular schedules)
CREATE TABLE hospital_holidays (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    hospital_id VARCHAR(36) NOT NULL,
    holiday_date DATE NOT NULL,
    name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_holidays_hospital FOREIGN KEY (hospital_id) REFERENCES hospitals(id) ON DELETE CASCADE,
    UNIQUE KEY uq_hospital_holiday (hospital_id, holiday_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 10. INSURANCE PROVIDERS (Insurance policies accepted by the multi-hospital network)
CREATE TABLE insurance_providers (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    hospital_id VARCHAR(36) NOT NULL,
    provider_name VARCHAR(150) NOT NULL,
    plan_name VARCHAR(150) NULL,
    network_status VARCHAR(50) DEFAULT 'IN_NETWORK' NOT NULL COMMENT 'IN_NETWORK, OUT_OF_NETWORK',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_insurance_hospital FOREIGN KEY (hospital_id) REFERENCES hospitals(id) ON DELETE CASCADE,
    INDEX idx_insurance_provider (provider_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 11. PATIENTS (Registered patients calling or scheduling)
CREATE TABLE patients (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    hospital_id VARCHAR(36) NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    date_of_birth DATE NOT NULL,
    gender VARCHAR(20) NULL,
    phone VARCHAR(20) NOT NULL,
    email VARCHAR(255) NULL,
    insurance_provider_id VARCHAR(36) NULL,
    insurance_policy_number VARCHAR(100) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_patients_hospital FOREIGN KEY (hospital_id) REFERENCES hospitals(id) ON DELETE CASCADE,
    CONSTRAINT fk_patients_insurance FOREIGN KEY (insurance_provider_id) REFERENCES insurance_providers(id) ON DELETE SET NULL,
    INDEX idx_patients_lookup (hospital_id, phone),
    INDEX idx_patients_identity (hospital_id, last_name, first_name, date_of_birth)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 12. APPOINTMENTS (Booked slots between patient and doctor)
CREATE TABLE appointments (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    hospital_id VARCHAR(36) NOT NULL,
    patient_id VARCHAR(36) NOT NULL,
    doctor_id VARCHAR(36) NOT NULL,
    appointment_datetime DATETIME NOT NULL,
    duration_minutes INT DEFAULT 30 NOT NULL,
    status VARCHAR(50) DEFAULT 'SCHEDULED' NOT NULL COMMENT 'SCHEDULED, CANCELLED, COMPLETED, NO_SHOW, PENDING_PAYMENT',
    reason TEXT NULL,
    source VARCHAR(50) DEFAULT 'VOICE' NOT NULL COMMENT 'VOICE, WEB, IN_PERSON',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_appointments_hospital FOREIGN KEY (hospital_id) REFERENCES hospitals(id) ON DELETE CASCADE,
    CONSTRAINT fk_appointments_patient FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
    CONSTRAINT fk_appointments_doctor FOREIGN KEY (doctor_id) REFERENCES doctors(id) ON DELETE RESTRICT,
    INDEX idx_appointments_time (hospital_id, doctor_id, appointment_datetime),
    INDEX idx_appointments_patient (patient_id),
    INDEX idx_appointments_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 13. APPOINTMENT_STATUS_HISTORY (Auditing trace of status transitions)
CREATE TABLE appointment_status_history (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    appointment_id VARCHAR(36) NOT NULL,
    previous_status VARCHAR(50) NULL,
    new_status VARCHAR(50) NOT NULL,
    changed_by_user_id VARCHAR(36) NULL COMMENT 'Null if changed by AI voice system',
    change_reason VARCHAR(255) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_status_history_appointment FOREIGN KEY (appointment_id) REFERENCES appointments(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 14. CALL_LOGS (Twilio incoming call parameters)
CREATE TABLE call_logs (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    hospital_id VARCHAR(36) NOT NULL,
    twilio_call_sid VARCHAR(100) NOT NULL UNIQUE,
    caller_number VARCHAR(20) NOT NULL,
    receiver_number VARCHAR(20) NOT NULL,
    call_status VARCHAR(50) NOT NULL COMMENT 'queued, ringing, in-progress, completed, failed, busy, no-answer',
    start_time DATETIME NULL,
    end_time DATETIME NULL,
    duration_seconds INT NULL,
    recording_url TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_call_logs_hospital FOREIGN KEY (hospital_id) REFERENCES hospitals(id) ON DELETE CASCADE,
    INDEX idx_call_logs_sid (twilio_call_sid),
    INDEX idx_call_logs_caller (caller_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 15. VOICE_SESSIONS (State mapping of individual voice conversation streams)
CREATE TABLE voice_sessions (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    call_log_id VARCHAR(36) NOT NULL,
    patient_id VARCHAR(36) NULL,
    gemini_session_id VARCHAR(100) NULL,
    session_status VARCHAR(50) DEFAULT 'ACTIVE' NOT NULL COMMENT 'ACTIVE, TERMINATED',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_voice_sessions_call FOREIGN KEY (call_log_id) REFERENCES call_logs(id) ON DELETE CASCADE,
    CONSTRAINT fk_voice_sessions_patient FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE SET NULL,
    INDEX idx_voice_sessions_gemini (gemini_session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 16. CONVERSATION_LOGS (Exact transcript lines of caller and AI speech)
CREATE TABLE conversation_logs (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    voice_session_id VARCHAR(36) NOT NULL,
    speaker VARCHAR(50) NOT NULL COMMENT 'CALLER, AI_RECEPTIONIST',
    transcript TEXT NOT NULL,
    confidence_score DECIMAL(5,4) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_conversation_logs_session FOREIGN KEY (voice_session_id) REFERENCES voice_sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 17. CONVERSATION_MEMORY (Summaries or metadata stored from the conversation)
CREATE TABLE conversation_memory (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    voice_session_id VARCHAR(36) NOT NULL,
    memory_type VARCHAR(50) NOT NULL COMMENT 'SUMMARY, EXTRACTED_ENTITIES, INSIGHT',
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_conv_memory_session FOREIGN KEY (voice_session_id) REFERENCES voice_sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 18. TOOL_EXECUTION_LOGS (Trace logs of function calling executed by Gemini)
CREATE TABLE tool_execution_logs (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    voice_session_id VARCHAR(36) NOT NULL,
    tool_name VARCHAR(100) NOT NULL,
    arguments TEXT NOT NULL COMMENT 'JSON payload of input arguments',
    response TEXT NULL COMMENT 'JSON payload of result',
    execution_status VARCHAR(50) NOT NULL COMMENT 'SUCCESS, FAILED',
    execution_time_ms INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_tool_logs_session FOREIGN KEY (voice_session_id) REFERENCES voice_sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 19. DOCTOR_AVAILABILITY_CACHE (Optimized table for fast query of free slots)
CREATE TABLE doctor_availability_cache (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    doctor_id VARCHAR(36) NOT NULL,
    available_date DATE NOT NULL,
    slot_start_time TIME NOT NULL,
    slot_end_time TIME NOT NULL,
    is_booked BOOLEAN DEFAULT FALSE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_availability_doctor FOREIGN KEY (doctor_id) REFERENCES doctors(id) ON DELETE CASCADE,
    UNIQUE KEY uq_doc_slot (doctor_id, available_date, slot_start_time),
    INDEX idx_avail_lookup (doctor_id, available_date, is_booked)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 20. PAYMENT_LINKS (Generated for patient check-in or appointment copayments)
CREATE TABLE payment_links (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    appointment_id VARCHAR(36) NOT NULL,
    payment_url TEXT NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD' NOT NULL,
    status VARCHAR(50) DEFAULT 'PENDING' NOT NULL COMMENT 'PENDING, PAID, EXPIRED',
    expires_at DATETIME NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_payment_links_appointment FOREIGN KEY (appointment_id) REFERENCES appointments(id) ON DELETE CASCADE,
    INDEX idx_payment_links_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 21. PAYMENTS (Transactions tied to payment links)
CREATE TABLE payments (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    payment_link_id VARCHAR(36) NOT NULL,
    transaction_reference VARCHAR(150) NOT NULL UNIQUE,
    gateway VARCHAR(50) NOT NULL COMMENT 'STRIPE, PAYPAL, AUTHORIZE_NET',
    amount_paid DECIMAL(10,2) NOT NULL,
    payment_status VARCHAR(50) NOT NULL COMMENT 'SUCCESS, FAILED, REFUNDED',
    paid_at DATETIME NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_payments_link FOREIGN KEY (payment_link_id) REFERENCES payment_links(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 22. NOTIFICATIONS (Queued communications for SMS, email or voice outbound dial)
CREATE TABLE notifications (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    hospital_id VARCHAR(36) NOT NULL,
    recipient_type VARCHAR(50) NOT NULL COMMENT 'PATIENT, DOCTOR, STAFF',
    recipient_id VARCHAR(36) NOT NULL COMMENT 'Polymorphic identifier based on recipient_type',
    channel VARCHAR(50) NOT NULL COMMENT 'SMS, EMAIL, VOICE',
    template_name VARCHAR(100) NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_notifications_hospital FOREIGN KEY (hospital_id) REFERENCES hospitals(id) ON DELETE CASCADE,
    INDEX idx_notifications_recipient (recipient_type, recipient_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 23. NOTIFICATION_LOGS (Outbound logs with provider trace details)
CREATE TABLE notification_logs (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    notification_id VARCHAR(36) NOT NULL,
    provider VARCHAR(50) NOT NULL COMMENT 'TWILIO, SENDGRID, AWS_SES',
    provider_message_sid VARCHAR(100) NULL UNIQUE,
    status VARCHAR(50) NOT NULL COMMENT 'SENT, DELIVERED, FAILED',
    error_message TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_notification_logs_parent FOREIGN KEY (notification_id) REFERENCES notifications(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 24. USERS (Hospital admin panel and management system dashboard users)
CREATE TABLE users (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    hospital_id VARCHAR(36) NULL COMMENT 'Null indicates multi-hospital super administrator',
    username VARCHAR(100) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    first_name VARCHAR(100) NULL,
    last_name VARCHAR(100) NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_users_hospital FOREIGN KEY (hospital_id) REFERENCES hospitals(id) ON DELETE CASCADE,
    INDEX idx_users_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 25. ROLES (RBAC Roles for admin interfaces)
CREATE TABLE roles (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE COMMENT 'SUPER_ADMIN, HOSPITAL_ADMIN, RECEPTIONIST, CLINIC_STAFF',
    description VARCHAR(255) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 26. PERMISSIONS (Granular operation descriptors)
CREATE TABLE permissions (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    code VARCHAR(100) NOT NULL UNIQUE COMMENT 'APPOINTMENT_CREATE, CALL_VIEW, USER_MANAGE, PATIENT_READ',
    description VARCHAR(255) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Mapped Relation: ROLE_PERMISSIONS (Connects permissions to roles)
CREATE TABLE role_permissions (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    role_id VARCHAR(36) NOT NULL,
    permission_id VARCHAR(36) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_rp_role FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
    CONSTRAINT fk_rp_permission FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE CASCADE,
    UNIQUE KEY uq_role_permission (role_id, permission_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 27. USER_ROLES (Maps users to roles)
CREATE TABLE user_roles (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    role_id VARCHAR(36) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_ur_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_ur_role FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
    UNIQUE KEY uq_user_role (user_id, role_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 28. AUDIT_LOGS (Operational tracks of admin console behaviors)
CREATE TABLE audit_logs (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    user_id VARCHAR(36) NULL COMMENT 'Null if action occurred through anonymous API',
    action VARCHAR(100) NOT NULL,
    ip_address VARCHAR(45) NULL,
    payload JSON NULL COMMENT 'Structured log parameters',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_audit_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 29. KNOWLEDGE_BASE (General hospital information, routing instructions, and guide policies for RAG context)
CREATE TABLE knowledge_base (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    hospital_id VARCHAR(36) NOT NULL,
    title VARCHAR(255) NOT NULL,
    content LONGTEXT NOT NULL,
    category VARCHAR(100) NULL COMMENT 'POLICIES, DIRECTIONS, EMERGENCY_GUIDES',
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_kb_hospital FOREIGN KEY (hospital_id) REFERENCES hospitals(id) ON DELETE CASCADE,
    INDEX idx_kb_category (hospital_id, category),
    FULLTEXT KEY ft_kb_search (title, content)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 30. FAQS (Flat question-answer key blocks for direct AI search query injection)
CREATE TABLE faqs (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    hospital_id VARCHAR(36) NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    category VARCHAR(100) NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_faqs_hospital FOREIGN KEY (hospital_id) REFERENCES hospitals(id) ON DELETE CASCADE,
    INDEX idx_faqs_category (hospital_id, category),
    FULLTEXT KEY ft_faqs_search (question, answer)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
