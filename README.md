# AI Voice Receptionist - Modular Scalable Clean Architecture

A production-ready FastAPI backend designed to serve as an AI Voice Receptionist for hospitals, adhering to Clean Architecture principles.

## Core Architectural Boundaries

The application is structured to decouple domain logic from external libraries, database persistence, and communication gateways.

- **Presentation Layer (`app/api`)**: FastAPI controllers, route handlers, and middleware.
- **Application Layer (`app/engines`, `app/managers`)**: Houses use-case engines (Decision, Scheduling, Memory, Appointment) and orchestration managers (Prompt, Conversation).
- **Domain Layer (`app/domain`)**: Contains pure business objects and entities independent of framework or database details.
- **Infrastructure Layer (`app/database`, `app/services`)**: Deals with database connections (SQLAlchemy), Alembic migrations, and outbound services (Twilio, Gemini Live/Function Calling API, n8n webhook automation).
- **Core Configuration (`app/core`)**: Structured logging, custom exception handling, and application configurations.

## Folder Directory Structure

```text
├── .dockerignore
├── .env.example
├── .gitignore
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
│   │   ├── dependencies.py
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
│   │   ├── gemini_service.py
│   │   └── twilio_service.py
│   └── utils/
│       ├── __init__.py
│       └── helpers.py
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

## Component Mapping

1. **API**: `app/api/v1/` routes handling Twilio voice calls, n8n webhooks, and management portals.
2. **Services**: Interfaces and client wrappers for remote APIs under `app/services/`.
3. **Database**: Database session managers and connection pool configurations in `app/database/`.
4. **Models**: Domain Entities (`app/domain/models.py`) and SQLAlchemy ORM Models (`app/database/models/`).
5. **Schemas**: Pydantic input/output schemas in `app/schemas/` representing interface adapter contract validation.
6. **Prompt Manager**: `app/managers/prompt.py` dynamically handles voice prompt assembly, tone maintenance (strictly professional receptionist), and safety instructions (no politics, medical advice, programming, etc.).
7. **Conversation Manager**: `app/managers/conversation.py` handles audio streams and text turns, maintaining context window state.
8. **Decision Engine**: `app/engines/decision.py` performs intent extraction and determines agent actions (e.g. speak response, transfer call, schedule appointment).
9. **Scheduling Engine**: `app/engines/scheduling.py` parses temporal parameters, matches free/busy blocks, and checks appointment availability.
10. **Appointment Engine**: `app/engines/appointment.py` encapsulates logic for booking, modifying, or cancelling appointments.
11. **Memory Engine**: `app/engines/memory.py` retrieves historical records, patient profiles, and context-relevant logs.
12. **Automation Service**: `app/services/automation.py` communicates with n8n webhook workflows for integration tasks.
13. **Twilio Service**: `app/services/twilio_service.py` crafts dynamic TwiML and manages stream connections.
14. **Gemini Service**: `app/services/gemini_service.py` maps Gemini API client logic for structured function-calling and multimodal live interactions.
15. **Utilities**: `app/utils/` standard date formatters, parsing helpers, and general utilities.
16. **Config**: `app/core/config.py` application settings parsing credentials safely.
17. **Logging**: `app/core/logging.py` logs system metrics, call status, latency, and trace IDs.
18. **Exception Handling**: `app/core/exceptions.py` global error mapping, response standardizations, and custom domain errors.
