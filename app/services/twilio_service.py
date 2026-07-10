import asyncio
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Dial, Stream
from app.core.config import settings
from app.core.logging import twilio_logger
from app.core.exceptions import ThirdPartyException

class TwilioService:
    def __init__(self):
        # Initialize Twilio Client
        self.client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        self.phone_number = settings.TWILIO_PHONE_NUMBER

    def generate_websocket_stream_twiml(self, voice_session_id: str) -> str:
        """Generates TwiML to hook up the call audio to our FastAPI websocket streaming server."""
        twilio_logger.info(f"Generating WebSocket stream TwiML for voice session: {voice_session_id}")
        response = VoiceResponse()
        
        # Say a brief intro text in Hindi
        response.say("सी पी तिवारी हॉस्पिटल में आपका स्वागत है। कृपया प्रतीक्षा करें, हम आपको वर्चुअल असिस्टेंट से कनेक्ट कर रहे हैं।", voice="Polly.Aditi", language="hi-IN")
        
        # Start bidirectional media stream
        # Twilio sends base64 encoded audio payloads via WS
        clean_webhook_url = settings.TWILIO_WEBHOOK_URL.strip().rstrip("/")
        domain = clean_webhook_url.replace("https://", "").replace("http://", "")
        from twilio.twiml.voice_response import Connect
        connect = Connect()
        connect.stream(
            url=f"wss://{domain}/api/v1/voice/stream/{voice_session_id}",
            name=f"session_{voice_session_id}"
        )
        response.append(connect)
        
        # Prevent call from hanging up immediately if stream ends prematurely
        response.pause(length=30)
        return str(response)

    def generate_transfer_twiml(self, transfer_number: str, message: str) -> str:
        """Generates TwiML to speak a transfer notice and dial an external phone number (e.g., ER or 911)."""
        twilio_logger.info(f"Generating call transfer TwiML to destination: {transfer_number}")
        response = VoiceResponse()
        response.say(message, voice="Polly.Joanna-Neural")
        
        dial = Dial()
        dial.number(transfer_number)
        response.append(dial)
        return str(response)

    async def send_sms_async(self, to_number: str, body: str) -> str:
        """Sends an SMS message asynchronously using asyncio.to_thread to prevent event loop blocking."""
        twilio_logger.info(f"Sending SMS alert to {to_number}")
        
        def _send():
            message = self.client.messages.create(
                body=body,
                from_=self.phone_number,
                to=to_number
            )
            return message.sid

        try:
            message_sid = await asyncio.to_thread(_send)
            twilio_logger.info(f"SMS successfully sent. Message SID: {message_sid}")
            return message_sid
        except Exception as e:
            twilio_logger.error(f"Failed to dispatch SMS notification via Twilio: {str(e)}")
            raise ThirdPartyException(f"Twilio SMS gateway failed: {str(e)}")

    async def initiate_outbound_call_async(self, to_number: str, webhook_domain: str) -> str:
        """Initiates an outbound call asynchronously using Twilio Calls API."""
        clean_domain = webhook_domain.strip().rstrip("/")
        domain = clean_domain.replace("https://", "").replace("http://", "")
        voice_url = f"https://{domain}/api/v1/voice/inbound"
        twilio_logger.info(f"Initiating outbound call to {to_number} targeting Webhook: {voice_url}")

        def _call():
            call = self.client.calls.create(
                to=to_number,
                from_=self.phone_number,
                url=voice_url
            )
            return call.sid

        try:
            call_sid = await asyncio.to_thread(_call)
            twilio_logger.info(f"Outbound call successfully initiated. Call SID: {call_sid}")
            return call_sid
        except Exception as e:
            twilio_logger.error(f"Failed to initiate outbound call via Twilio: {str(e)}")
            raise ThirdPartyException(f"Twilio Calls gateway failed: {str(e)}")
            
    def generate_hangup_twiml(self, message: str) -> str:
        """Generates TwiML to play a message and hang up the call."""
        response = VoiceResponse()
        response.say(message, voice="Polly.Joanna-Neural")
        response.hangup()
        return str(response)
