import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from app.core.config import settings

# Create log directory if it does not exist
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "hospital_voice_receptionist.log"

def setup_logging():
    """Sets up standard output and rotating file logging for the application."""
    log_format = (
        "[%(asctime)s] %(levelname)s [%(name)s:%(metadata)s] [%(filename)s:%(lineno)d] - %(message)s"
    )
    
    # Custom filter to inject trace/metadata if needed, ensuring format consistency
    class TraceFilter(logging.Filter):
        def filter(self, record):
            if not hasattr(record, "metadata"):
                record.metadata = "SYSTEM"
            return True

    # Root Logger Setup
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    
    # Prevent duplicate handlers if re-initialized
    if root_logger.handlers:
        root_logger.handlers.clear()

    # Stream Handler (Stdout)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(logging.Formatter(log_format))
    stdout_handler.addFilter(TraceFilter())
    root_logger.addHandler(stdout_handler)

    # File Handler (Rotating)
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=10485760, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(log_format))
    file_handler.addFilter(TraceFilter())
    root_logger.addHandler(file_handler)

    # Suppress verbose third-party libraries logging in production
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("aiomysql").setLevel(logging.WARNING)
    logging.getLogger("twilio").setLevel(logging.INFO)

    logging.info("Logging infrastructure successfully initialized.")

setup_logging()

# Export specific loggers for tracking subsystems
logger = logging.getLogger("app")
twilio_logger = logging.getLogger("app.twilio")
gemini_logger = logging.getLogger("app.gemini")
engine_logger = logging.getLogger("app.engine")
db_logger = logging.getLogger("app.db")
audit_logger = logging.getLogger("app.audit")
