import asyncio
from twilio.rest import Client
from app.core.config import settings

def check_whatsapp():
    print("Checking Twilio WhatsApp message logs...")
    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    try:
        messages = client.messages.list(limit=5)
        for msg in messages:
            body_safe = msg.body.encode('ascii', errors='ignore').decode('ascii')
            err_msg_safe = (msg.error_message or '').encode('ascii', errors='ignore').decode('ascii')
            print(f"SID: {msg.sid}, To: {msg.to}, From: {msg.from_}, Status: {msg.status}, ErrorCode: {msg.error_code}, ErrorMsg: {err_msg_safe}, Body: {body_safe[:60]}...")
    except Exception as e:
        print(f"Error checking logs: {str(e)}")

if __name__ == "__main__":
    check_whatsapp()
