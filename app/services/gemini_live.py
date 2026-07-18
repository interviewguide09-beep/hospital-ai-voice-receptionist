import asyncio
import base64
import json
from typing import AsyncGenerator, Callable, Dict, Any, Optional
import websockets
from app.core.config import settings
from app.core.logging import gemini_logger

class GeminiLiveClient:
    def __init__(self, system_instruction: str):
        self.api_key = settings.GEMINI_API_KEY
        self.model = "models/gemini-2.5-flash-native-audio-latest"  # Live API model
        self.uri = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key={self.api_key}"
        self.system_instruction = system_instruction
        self.connection = None

    async def connect(self) -> None:
        """Establishes the WebSocket connection to the Gemini Live API and sends the initial setup payload."""
        gemini_logger.info("Connecting to Gemini Live API WebSocket...")
        self.connection = await websockets.connect(self.uri)
        
        # Send Setup Configuration payload
        setup_message = {
            "setup": {
                "model": self.model,
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "voiceConfig": {
                            "prebuiltVoiceConfig": {
                                "voiceName": "Kore"  # Kore: clear feminine voice with good Hindi pronunciation
                            }
                        },
                        "languageCode": "hi-IN"  # Force Hindi Indian language mode
                    }
                },
                "realtimeInputConfig": {
                    "automaticActivityDetection": {
                        "disabled": False,
                        "startOfSpeechSensitivity": "START_SENSITIVITY_HIGH",  # Detect user speech instantly
                        "endOfSpeechSensitivity": "END_SENSITIVITY_HIGH",     # Detect end of speech quickly
                        "prefixPaddingMs": 100,
                        "silenceDurationMs": 400   # 0.4s silence = turn done (fast response)
                    }
                },
                "tools": [
                    {
                        "functionDeclarations": [
                            {
                                "name": "check_availability",
                                "description": "Check available appointment slots for a specific doctor on a given date. Call this BEFORE booking to show the patient which time slots are free.",
                                "parameters": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "doctor_id": {
                                            "type": "STRING",
                                            "description": "The unique ID of the doctor. Use: doc_ortho for Orthopedics/Haddi, doc_cardio for Cardiology/Heart, doc_eye for Ophthalmology/Eye"
                                        },
                                        "date": {
                                            "type": "STRING",
                                            "description": "The date to check availability for, in YYYY-MM-DD format (e.g. 2024-07-10)"
                                        }
                                    },
                                    "required": ["doctor_id", "date"]
                                }
                            },
                            {
                                "name": "book_appointment",
                                "description": "Book a confirmed appointment after the patient has agreed to a specific slot. Only call this AFTER patient verbally confirms the details.",
                                "parameters": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "patient_name": {
                                            "type": "STRING",
                                            "description": "Full name of the patient as spoken during the call"
                                        },
                                        "doctor_id": {
                                            "type": "STRING",
                                            "description": "The unique ID of the doctor. Use: doc_ortho, doc_cardio, or doc_eye"
                                        },
                                        "appointment_datetime": {
                                            "type": "STRING",
                                            "description": "The exact appointment date and time in ISO format: YYYY-MM-DDTHH:MM:SS (e.g. 2024-07-10T09:10:00)"
                                        },
                                        "reason": {
                                            "type": "STRING",
                                            "description": "Brief reason for the appointment as described by the patient"
                                        }
                                    },
                                    "required": ["patient_name", "doctor_id", "appointment_datetime"]
                                }
                            },
                            {
                                "name": "save_patient_intake",
                                "description": "Save the medical history and intake information collected from the patient during the post-payment intake call. Call this ONCE when you have gathered all the information.",
                                "parameters": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "appointment_id": {
                                            "type": "STRING",
                                            "description": "The appointment ID for which intake is being collected"
                                        },
                                        "has_visited_before": {
                                            "type": "BOOLEAN",
                                            "description": "Whether the patient has visited any doctor for this problem before (true/false)"
                                        },
                                        "previous_doctor": {
                                            "type": "STRING",
                                            "description": "Name or hospital where patient previously consulted, if any"
                                        },
                                        "has_reports": {
                                            "type": "BOOLEAN",
                                            "description": "Whether the patient has any medical reports or test results (true/false)"
                                        },
                                        "report_details": {
                                            "type": "STRING",
                                            "description": "Details about what reports the patient has"
                                        },
                                        "current_medicines": {
                                            "type": "STRING",
                                            "description": "Any medicines the patient is currently taking"
                                        },
                                        "additional_notes": {
                                            "type": "STRING",
                                            "description": "Any other relevant information shared by the patient"
                                        }
                                    },
                                    "required": ["appointment_id"]
                                }
                            }
                        ]
                    }
                ],
                "systemInstruction": {
                    "parts": [{"text": self.system_instruction}]
                }
            }
        }
        await self.connection.send(json.dumps(setup_message))
        gemini_logger.info("Sent initial setup payload to Gemini Live API.")

    async def send_audio_chunk(self, base64_pcm_data: str) -> None:
        """Sends a 16kHz PCM audio chunk (base64 encoded) to the Gemini Live stream."""
        if not self.connection:
            gemini_logger.error("Cannot send audio: Gemini Live connection is not open.")
            return

        media_message = {
            "realtimeInput": {
                "mediaChunks": [
                    {
                        "mimeType": "audio/pcm;rate=16000",
                        "data": base64_pcm_data
                    }
                ]
            }
        }
        await self.connection.send(json.dumps(media_message))

    async def send_text_trigger(self, text: str) -> None:
        """Sends a text prompt turns payload to trigger a model response."""
        if not self.connection:
            gemini_logger.error("Cannot send text trigger: Gemini Live connection is not open.")
            return

        trigger_message = {
            "clientContent": {
                "turns": [
                    {
                        "role": "user",
                        "parts": [{"text": text}]
                    }
                ],
                "turnComplete": True
            }
        }
        await self.connection.send(json.dumps(trigger_message))
        gemini_logger.info(f"Sent text trigger to Gemini Live API: {text}")

    async def receive_stream(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Listens to the Gemini Live response WebSocket, yielding audio frames and tool calls."""
        if not self.connection:
            gemini_logger.error("Cannot receive stream: Gemini Live connection is not open.")
            return

        try:
            async for raw_message in self.connection:
                # Log that we received a message (either text or binary/protobuf)
                if isinstance(raw_message, bytes):
                    gemini_logger.debug(f"Received binary message from Gemini of size {len(raw_message)} bytes")
                    # Try decoding it if it's JSON encoded as bytes
                    try:
                        message = json.loads(raw_message.decode("utf-8"))
                    except Exception:
                        gemini_logger.warning("Could not parse binary message as JSON UTF-8")
                        continue
                else:
                    gemini_logger.debug(f"Received text message from Gemini: {raw_message[:200]}")
                    message = json.loads(raw_message)
                
                # Check for toolCall from Gemini (for Multimodal Live API tool executions)
                tool_call = message.get("toolCall")
                if tool_call:
                    gemini_logger.info(f"Received toolCall event from Gemini: {list(tool_call.keys())}")
                    function_calls = tool_call.get("functionCalls", [])
                    for fc in function_calls:
                        gemini_logger.info(f"Yielding functionCall: {fc.get('name')} with ID: {fc.get('id')}")
                        yield {
                            "type": "function_call",
                            "id": fc.get("id"),
                            "name": fc.get("name"),
                            "args": fc.get("args")
                        }

                # Check for audio chunks from Gemini
                server_content = message.get("serverContent")
                if server_content:
                    gemini_logger.info(f"Received serverContent: {list(server_content.keys())}")
                    if server_content.get("turnComplete"):
                        yield {"type": "turn_complete"}
                    if server_content.get("interrupted"):
                        yield {"type": "interrupted"}
                    model_turn = server_content.get("modelTurn")
                    if model_turn:
                        parts = model_turn.get("parts", [])
                        gemini_logger.info(f"Received modelTurn parts count: {len(parts)}")
                        for part in parts:
                            inline_data = part.get("inlineData")
                            if inline_data:
                                mime_type = inline_data.get("mimeType", "")
                                gemini_logger.debug(f"Part inlineData mimeType: {mime_type}, data size: {len(inline_data.get('data', ''))}")
                                if mime_type.startswith("audio/pcm"):
                                    yield {
                                        "type": "audio",
                                        "data": inline_data["data"],  # Base64 PCM data (typically 24kHz)
                                        "rate": 24000
                                    }
                            
                            # Handle tool call requests in-stream
                            function_call = part.get("functionCall")
                            if function_call:
                                gemini_logger.info(f"Part functionCall: {function_call.get('name')}")
                                yield {
                                    "type": "function_call",
                                    "id": function_call.get("id"),
                                    "name": function_call.get("name"),
                                    "args": function_call.get("args")
                                }
                                
                # Check for stream signal (e.g. model finished speaking or user interrupted)
                # Gemini Live sends signals indicating turn status
                if "contentSignal" in message:
                    signal = message["contentSignal"]
                    if signal.get("type") == "INTERRUPT":
                        yield {"type": "interrupted"}
                        
        except websockets.exceptions.ConnectionClosed:
            gemini_logger.info("Gemini Live API connection closed normally.")
        except Exception as e:
            gemini_logger.error(f"Error in Gemini Live receive loop: {str(e)}")
            raise e

    async def send_tool_response(self, call_id: str, name: str, output: Dict[str, Any]) -> None:
        """Dispatches the result of a function call tool back to Gemini to resume the voice stream."""
        if not self.connection:
            return

        response_message = {
            "toolResponse": {
                "functionResponses": [
                    {
                        "id": call_id,
                        "name": name,
                        "response": output
                    }
                ]
            }
        }
        await self.connection.send(json.dumps(response_message))
        gemini_logger.info(f"Dispatched tool response for call_id: {call_id}, name: {name}")

    async def close(self) -> None:
        """Closes the active WebSocket connection to the Gemini API."""
        if self.connection:
            await self.connection.close()
            gemini_logger.info("Gemini Live connection successfully closed.")
            self.connection = None
