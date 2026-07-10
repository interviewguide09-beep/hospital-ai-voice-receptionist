# Technical Audit Report - Hospital AI Voice Receptionist

This document provides a comprehensive technical audit of the entire Hospital AI Voice Receptionist codebase, illustrating the folder structure, package dependencies, environment configurations, application routers, endpoints, service integrations, and known configuration issues.

---

## 1. Complete Project Tree

The folder structure of the repository is organized as follows:

```text
C:\Users\shiva\Desktop\AAA/
├── .dockerignore
├── .env
├── .env.example
├── Dockerfile
├── README.md
├── alembic.ini
├── docker-compose.yml
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py
│   │       └── endpoints/
│   │           ├── __init__.py
│   │           ├── appointments.py
│   │           └── voice.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── dependencies.py
│   │   ├── exceptions.py
│   │   └── logging.py
│   ├── database/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── session.py
│   │   └── models/
│   │       ├── __init__.py
│   │       ├── appointment.py
│   │       ├── call_log.py
│   │       └── conversation.py
│   ├── domain/
│   │   ├── __init__.py
│   │   └── models.py
│   ├── engines/
│   │   ├── __init__.py
│   │   ├── appointment.py
│   │   ├── decision.py
│   │   ├── memory.py
│   │   └── scheduling.py
│   ├── managers/
│   │   ├── __init__.py
│   │   ├── conversation.py
│   │   └── prompt.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── appointment.py
│   │   ├── conversation.py
│   │   └── twilio.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── automation.py
│   │   ├── gemini_live.py
│   │   ├── gemini_service.py
│   │   └── twilio_service.py
│   └── utils/
│       ├── __init__.py
│       ├── audio.py
│       └── helpers.py
├── docs/
│   ├── ai_brain_design.md
│   └── technical_audit.md
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── .gitkeep
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── integration/
    │   └── __init__.py
    └── unit/
        └── __init__.py
```

---

## 2. requirements.txt

The complete contents of the [requirements.txt](file:///c:/Users/shiva/Desktop/AAA/requirements.txt) file:

```text
fastapi>=0.111.0
uvicorn[standard]>=0.30.0
pydantic[email]>=2.7.0
pydantic-settings>=2.3.0
sqlalchemy[asyncio]>=2.0.30
aiomysql>=0.2.0
cryptography>=42.0.0
pyjwt[crypto]>=2.8.0
passlib[bcrypt]>=1.7.4
google-generativeai>=0.5.4
twilio>=9.1.0
httpx>=0.27.0
alembic>=1.13.0
python-multipart>=0.0.9
pytest>=8.2.0
pytest-asyncio>=0.23.0
python-dotenv>=1.0.1
websockets>=12.0
```

---

## 3. .env Configuration Variables

Below is the list of environment variables declared in [.env](file:///c:/Users/shiva/Desktop/AAA/.env) along with their usage and requirement status:

*   **`PROJECT_NAME`**: (Required) Loaded by settings, sets FastAPI title. Value: `Hospital AI Voice Receptionist`.
*   **`ENV`**: (Required) Operational environment. Value: `development`.
*   **`DEBUG`**: (Required) Enables verbose logging and exception stack traces. Value: `True`.
*   **`MYSQL_HOST`**: (Required) Database host. Value: `mysql.railway.internal`.
*   **`MYSQL_PORT`**: (Required) Database port. Value: `3306`.
*   **`MYSQL_USER`**: (Required) Database user. Value: `root`.
*   **`MYSQL_PASSWORD`**: (Required) Database credentials. Value: `ln1pq***************`.
*   **`MYSQL_DATABASE`**: (Required) Database schema name. Value: `railway`.
*   **`JWT_SECRET_KEY`**: (Required) Cryptographic secret for signing tokens. Value: `e83a7***************`.
*   **`ACCESS_TOKEN_EXPIRE_MINUTES`**: (Optional) Token lifetime. Value: `1440` (24 Hours).
*   **`GEMINI_API_KEY`**: (Required) Key used by Gemini Services. Value: `AQ.Ab***************`.
*   **`GEMINI_MODEL`**: (Optional) Default fallback model. Value: `gemini-2.5-flash`.
*   **`TWILIO_ACCOUNT_SID`**: (Required) Twilio identity. Value: `AC953***************`.
*   **`TWILIO_PHONE_NUMBER`**: (Required) Virtual phone number. Value: `+12182070294`.
*   **`TWILIO_AUTH_TOKEN`**: (Required) Twilio credentials. Value: `deb0d***************`.
*   **`TWILIO_WEBHOOK_URL`**: (Required) The ngrok tunnel or domain forwarding websocket traffic. Value: `your-public-ngrok-tunnel.ngrok-free.app`.
*   **`N8N_WEBHOOK_URL`**: (Required) Webhook target for appointment alerts. Value: `https://interview09.app.n8n.cloud/webhook/81fcf42b-8e16-4cb4-818b-a9c086becfba`.
*   **`N8N_API_KEY`**: (Optional) Authentication header token. Value: Empty.
*   **Unused variables**: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `EMAIL_FROM` (Not required as n8n handles outbox SMTP integrations).

---

## 4. FastAPI Core Structure

### main.py Implementation
The file [app/main.py](file:///c:/Users/shiva/Desktop/AAA/app/main.py) acts as the initialization layer:
*   **Startup Events**: Logs system readiness through `create_app()` factory patterns.
*   **Middleware**: Configures `CORSMiddleware` (injects origins from `settings.BACKEND_CORS_ORIGINS`).
*   **Router**: Includes `api_router` from `app.api.v1.router` with prefix `/api/v1`.
*   **CORS Configuration**: Binds allowed origins, HTTP methods, headers, and credential flags.
*   **Exception Handlers**: Hooks `register_exception_handlers(app)` (maps customized domain exceptions to standard API JSONs).

### Dependencies
Exposed in [app/core/dependencies.py](file:///c:/Users/shiva/Desktop/AAA/app/core/dependencies.py):
*   `get_db`: Yields async database sessions.
*   `get_current_user`: Secures endpoints by validating the authorization token against user registries in the database.

---

## 5. Every API Route

| URL Path | Method | Input Schema | Output Schema | File Handler | Service Called |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `/api/v1/health` | `GET` | None | `{status, environment, project}` | `main.py` | None |
| `/api/v1/auth/login` | `POST` | `OAuth2PasswordRequestForm` | `{"access_token", "token_type"}` | `endpoints/appointments.py` | None |
| `/api/v1/appointments` | `POST` | `AppointmentCreate` | `AppointmentRead` | `endpoints/appointments.py` | `AppointmentEngine` |
| `/api/v1/appointments/{id}`| `DELETE`| None | `AppointmentRead` | `endpoints/appointments.py` | `AppointmentEngine` |
| `/api/v1/appointments/availability`| `GET` | `doctor_id`, `target_date` | `AvailableSlotsResponse` | `endpoints/appointments.py` | `SchedulingEngine` |
| `/api/v1/doctors` | `POST` | `DoctorCreate` | `DoctorRead` | `endpoints/appointments.py` | None (Direct DB Write) |
| `/api/v1/doctors` | `GET` | None | `List[DoctorRead]` | `endpoints/appointments.py` | None (Direct DB Read) |
| `/api/v1/patients` | `POST` | `PatientCreate` | `PatientRead` | `endpoints/appointments.py` | None (Direct DB Write) |
| `/api/v1/voice/inbound` | `POST` | `TwilioVoiceRequest` (Form) | XML (TwiML redirect payload) | `endpoints/voice.py` | `TwilioService` |
| `/api/v1/voice/stream/{id}` | `WS` | Binary/JSON (Twilio frame) | JSON (TwiML frame) | `endpoints/voice.py` | `GeminiLiveClient` |

---

## 6. Database Layer

*   **declarative Base**: Defined in [app/database/base.py](file:///c:/Users/shiva/Desktop/AAA/app/database/base.py) as `class Base(DeclarativeBase): pass`.
*   **Session Management**: Exposes `async_sessionmaker` bound to `mysql+aiomysql` and a sync engine for migrations inside [app/database/session.py](file:///c:/Users/shiva/Desktop/AAA/app/database/session.py).
*   **Models**:
    *   **[models/appointment.py](file:///c:/Users/shiva/Desktop/AAA/app/database/models/appointment.py)**: `Hospital`, `HospitalSetting`, `WorkingHour`, `Department`, `Doctor`, `DoctorSpecialization`, `DoctorSchedule`, `DoctorLeave`, `HospitalHoliday`, `InsuranceProvider`, `Patient`, `Appointment`, `AppointmentStatusHistory`.
    *   **[models/conversation.py](file:///c:/Users/shiva/Desktop/AAA/app/database/models/conversation.py)**: `CallLog`, `VoiceSession`, `ConversationLog`, `ConversationMemory`, `ToolExecutionLog`, `DoctorAvailabilityCache`, `KnowledgeBase`, `FAQ`.
    *   **[models/call_log.py](file:///c:/Users/shiva/Desktop/AAA/app/database/models/call_log.py)**: `PaymentLink`, `Payment`, `Notification`, `NotificationLog`, `User`, `Role`, `Permission`, `RolePermission`, `UserRole`, `AuditLog`.
*   **Relationships**: Multi-tenant database architecture. `Hospital` holds cascaded relationships to all child tables. `CallLog` maps bidirectionally to `Hospital.call_logs`.
*   **Migrations**: Alembic dynamically hooks connections in `migrations/env.py` to auto-discover model metadata registered on `Base.metadata`.

---

## 7. Circular Imports Check

*   **Identified Risks**: Circular dependencies can occur if models reference classes from other model files at import time (e.g., `appointment.py` importing `CallLog` from `call_log.py` while `call_log.py` imports `Appointment` from `appointment.py`).
*   **Mitigation**: 
    1.  **Lazy String References**: All SQLAlchemy relationships in the codebase use string references (e.g., `relationship("CallLog", back_populates="hospital")`) instead of direct class objects.
    2.  **Centralized Imports**: `app/database/base.py` imports all models sequentially *after* the `Base` class is fully defined. This ensures Alembic loads all tables in the correct order without circular dependency loops during initialization.

---

## 8. Services Audit

*   **Twilio Service**: Generates websocket-stream TwiML XMLs and sends non-blocking SMS notifications.
*   **Gemini Service**: Handles text intent classification and structured output schemas.
*   **Gemini Live Service**: Manages connection lifecycles over WebSockets to Google’s Multimodal Live API.
*   **Database Service**: Handles transactions and rolls back database sessions on failure.
*   **n8n Webhook Service**: Sends appointment confirmation payloads to external n8n webhook nodes.
*   **Appointment Engine**: Processes booking logic and updates DB records.
*   **Authentication Service**: Processes password verification and JWT issuance.

---

## 9. Twilio Call Routing Flow

```text
[Caller Phone] ──(PSTN Call)──> [Twilio Number +12182070294]
                                       │
                         (HTTP POST Webhook Request)
                                       ▼
                       [FastAPI /api/v1/voice/inbound]
                                       │
                        (Inserts CallLog & VoiceSession)
                                       ▼
                       [TwiML Response Returned to Twilio]
                     <Response><Connect><Stream url="..."/></Connect></Response>
                                       │
                         (Establishes WS Connection)
                                       ▼
               [FastAPI WS /api/v1/voice/stream/{session_id}]
```

*   **Webhook Configuration**: Configure the voice callback URL in your Twilio Console under Active Numbers to:
    `https://your-public-ngrok-tunnel.ngrok-free.app/api/v1/voice/inbound`

---

## 10. n8n Integrations

*   **Purpose**: n8n coordinates outbound notification workflows, email dispatches, and third-party calendar synchronizations (Google Calendar, Outlook) asynchronously, decoupling the FastAPI core loop from slow SMTP gateways.
*   **Payload sent to n8n**:
    ```json
    {
      "event": "appointment.booked",
      "timestamp": "2026-07-08T14:57:00Z",
      "data": {
        "appointment_id": "apt_uuid",
        "hospital_id": "hosp_uuid",
        "patient_id": "pat_uuid",
        "doctor_id": "doc_uuid",
        "appointment_datetime": "2026-07-09T10:00:00Z",
        "status": "SCHEDULED"
      }
    }
    ```
*   **Response expected**: HTTP status `200` / `201` / `202`.
*   **Can n8n be removed?**: Yes. You could replace it with a native Python background task engine (like Celery or FastAPI BackgroundTasks) that uses `aiosmtplib` and Google Calendar API clients. However, this increases code complexity and maintenance overhead.

---

## 11. AI Voice Pipeline Flow

```text
[User Speaks] 
    │ (Audio: G.711 mu-law, 8kHz)
    ▼
[Twilio Gateway]
    │ (WebSocket Media Frames)
    ▼
[FastAPI /stream/{session_id}]
    │ (1. Decodes mu-law bytes using lookup tables)
    │ (2. Resamples PCM from 8kHz to 16kHz via linear interpolation)
    ▼
[Gemini Live API WebSocket]
    │ (Evaluates VAD, runs tools, generates 24kHz PCM response)
    ▼
[FastAPI /stream/{session_id}]
    │ (1. Downsamples PCM from 24kHz to 8kHz)
    │ (2. Encodes PCM to mu-law bytes)
    ▼
[Twilio Gateway] 
    │ (Audio Playback)
    ▼
[User Hear Response]
```

---

## 12. Known Configuration Issues

*   **Railway Private Host Restriction**: `mysql.railway.internal` host can only be reached within Railway's internal container networks. Developers running migrations or running the server locally will receive connection timeout errors unless they use Railway's public TCP host.
*   **Missing explicitly locked dependencies**: `pymysql` and `cryptography` are resolved dynamically by Alembic/pyjwt, but need to be explicitly locked in `requirements.txt` to prevent dependency resolution issues in local development environments.

---

## 13. Deployment Strategies

*   **ngrok (Local Testing)**: Exposes FastAPI locally (port 8000) using a public HTTP forwarding tunnel. ngrok generates a secure HTTPS URL which is configured as the webhook target in the Twilio console.
*   **Railway (Production)**: The code uses the [Dockerfile](file:///c:/Users/shiva/Desktop/AAA/Dockerfile) to build the environment and [docker-compose.yml](file:///c:/Users/shiva/Desktop/AAA/docker-compose.yml) to deploy MySQL and FastAPI as a multi-service stack. Railway handles scaling, environment variable injections, and exposes a public endpoint.

---

## 14. Exact Operational Commands

```powershell
# 1. Install dependencies locally
pip install -r requirements.txt

# 2. Run migrations locally (Update local .env with public database credentials first)
alembic revision --autogenerate -m "Initial schema setup"
alembic upgrade head

# 3. Start local development server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 4. Start production services using Docker Compose
docker compose up --build -d

# 5. Run tests
pytest
```

---

## 15. Known Code Errors & Fixes

1.  **SQLAlchemy Relationship Mapping Exception**:
    *   *Error*: `CallLog.hospital` relation was mapped to target `back_populates="appointments"`, causing a startup metadata clash.
    *   *Fix*: Added the `call_logs` relationship to the `Hospital` model and corrected the target on the `CallLog` model to `back_populates="call_logs"`.
2.  **Missing `N8N_API_KEY` Validation Crash**:
    *   *Error*: The FastAPI application would fail to start if the `N8N_API_KEY` was missing from the environment.
    *   *Fix*: Made the parameter optional in `app/core/config.py` by providing a default value of `""`.

---

## 16. Technical Audit Checklist

### Configured Components (✔)
*   ✔ **FastAPI routers and startup configurations**: Working.
*   ✔ **Logging and custom exception routing**: Configured and working.
*   ✔ **Dynamic Prompt Manager compiling logic**: Configured.
*   ✔ **Twilio Service & TwiML response generation**: Configured.
*   ✔ **Gemini Live Client WebSocket stream protocol**: Configured.
*   ✔ **Pure-Python Audio decoding & linear resampling**: Configured.

### Undergoing Change (⚠)
*   ⚠ **Railway Database Connection**: Requires replacing the internal host `mysql.railway.internal` with Railway's public host in the local `.env` file to run migrations and test locally.
