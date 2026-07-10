from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from app.core.logging import logger

class BaseAppException(Exception):
    """Base exception class for all custom application errors."""
    def __init__(self, message: str, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)

class DatabaseException(BaseAppException):
    """Exception raised for database connectivity or constraint errors."""
    def __init__(self, message: str):
        super().__init__(message, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

class NotFoundException(BaseAppException):
    """Exception raised when a requested resource is not found."""
    def __init__(self, message: str):
        super().__init__(message, status_code=status.HTTP_404_NOT_FOUND)

class ValidationException(BaseAppException):
    """Exception raised when Pydantic, database, or engine verification fails."""
    def __init__(self, message: str):
        super().__init__(message, status_code=status.HTTP_400_BAD_REQUEST)

class AuthException(BaseAppException):
    """Exception raised for JWT authentication or permission failures."""
    def __init__(self, message: str, status_code: int = status.HTTP_401_UNAUTHORIZED):
        super().__init__(message, status_code=status_code)

class OutOfScopeException(BaseAppException):
    """Exception raised when LLM intent detection flags non-hospital topics."""
    def __init__(self, message: str):
        super().__init__(message, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)

class EmergencyException(BaseAppException):
    """Exception raised when clinical indicators flag an immediate triage redirect."""
    def __init__(self, message: str, transfer_number: str = "+1911"):
        self.transfer_number = transfer_number
        super().__init__(message, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

class ThirdPartyException(BaseAppException):
    """Exception raised when outbound calls to Gemini, Twilio or n8n fail."""
    def __init__(self, message: str):
        super().__init__(message, status_code=status.HTTP_502_BAD_GATEWAY)

def register_exception_handlers(app: FastAPI) -> None:
    """Registers global exception handlers for mapping core exceptions to JSON outputs."""
    
    @app.exception_handler(BaseAppException)
    async def base_app_exception_handler(request: Request, exc: BaseAppException):
        logger.error(f"Application Exception: {exc.message} | URL: {request.url.path}", extra={"metadata": "EXCEPTION"})
        return JSONResponse(
            status_code=exc.status_code,
            content={"success": False, "error": exc.message, "code": exc.__class__.__name__}
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.critical(f"Unhandled Server Error: {str(exc)} | URL: {request.url.path}", exc_info=True, extra={"metadata": "CRITICAL"})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": "An unexpected server error occurred.", "code": "UnhandledException"}
        )
