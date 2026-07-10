from typing import Optional
from pydantic import BaseModel, Field

class TwilioVoiceRequest(BaseModel):
    """Parses form-encoded Twilio request parameters during webhook voice callbacks."""
    CallSid: str = Field(..., description="Unique Twilio identifier for the active call")
    AccountSid: str = Field(..., description="Twilio Account owning the active call")
    From: str = Field(..., description="Caller identification phone number")
    To: str = Field(..., description="Receiver phone number (Hospital trunk line)")
    CallStatus: str = Field(..., description="Status of the voice stream session")
    Direction: str = Field("inbound", description="Call routing direction")
    ApiVersion: str = Field(..., description="Twilio API configuration version")
    SequenceNumber: Optional[int] = Field(None, description="Sequence count of the request hook")

class OutboundNotification(BaseModel):
    """Pydantic model defining configurations for sending SMS/outbound triggers."""
    hospital_id: str
    recipient_phone: str
    recipient_type: str = "PATIENT"  # PATIENT, DOCTOR, STAFF
    channel: str = "SMS"  # SMS, EMAIL, VOICE
    content: str
    template_name: Optional[str] = None
