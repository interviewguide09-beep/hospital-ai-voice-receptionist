import asyncio
import base64
import json
import uuid
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, Form, WebSocket, WebSocketDisconnect, Response, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.database.session import get_db
from app.database.models.conversation import CallLog, VoiceSession
from app.database.models.appointment import Hospital, Patient, Doctor
from app.services.twilio_service import TwilioService
from app.services.gemini_live import GeminiLiveClient
from app.utils.audio import ulaw_to_pcm, pcm_to_ulaw, resample_pcm
from app.engines.scheduling import SchedulingEngine
from app.engines.appointment import AppointmentEngine
from app.managers.prompt import PromptManager
from app.core.logging import twilio_logger
from app.core.config import settings

def calculate_amplitude(pcm_bytes: bytes) -> float:
    if not pcm_bytes:
        return 0.0
    import struct
    num_samples = len(pcm_bytes) // 2
    if num_samples == 0:
        return 0.0
    samples = struct.unpack(f"<{num_samples}h", pcm_bytes)
    return sum(abs(s) for s in samples) / num_samples

router = APIRouter()
twilio_service = TwilioService()

@router.post("/inbound")
async def handle_inbound_call(
    From: str = Form(...),
    To: str = Form(...),
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """Twilio incoming voice webhook endpoint. Initiates logs, creates session, and returns streaming TwiML response."""
    twilio_logger.info(f"Incoming call webhook received from caller: {From} to line: {To}")
    
    try:
        # 1. Resolve Hospital from To phone number or fallback to default by ID
        hospital_stmt = select(Hospital).where(Hospital.phone == To)
        hospital = (await db.execute(hospital_stmt)).scalar_one_or_none()
        
        if not hospital:
            # Check if default hospital already exists by ID
            default_stmt = select(Hospital).where(Hospital.id == "hosp_default")
            hospital = (await db.execute(default_stmt)).scalar_one_or_none()
            
            if not hospital:
                # Create it only if it doesn't exist by ID either
                hospital = Hospital(
                    id="hosp_default",
                    name="St. Mary General Hospital",
                    slug="st-mary-hospital",
                    phone=To,
                    is_active=True
                )
                db.add(hospital)
                await db.flush()
            else:
                # If it exists by ID but phone number is different, update the phone number
                if hospital.phone != To:
                    hospital.phone = To
                    await db.flush()
                    
        hospital_id = hospital.id

        # 3. Create Call Log Record
        call_log_id = str(uuid.uuid4())
        call_log = CallLog(
            id=call_log_id,
            hospital_id=hospital_id,
            twilio_call_sid=CallSid,
            caller_number=From,
            receiver_number=To,
            call_status=CallStatus,
            start_time=datetime.now(timezone.utc)
        )
        db.add(call_log)

        # 4. Create Voice Session Record
        voice_session_id = str(uuid.uuid4())
        voice_session = VoiceSession(
            id=voice_session_id,
            call_log_id=call_log_id,
            session_status="ACTIVE"
        )
        db.add(voice_session)
        await db.commit()

        # 5. Generate TwiML redirecting audio stream to WebSocket server
        twiml = twilio_service.generate_websocket_stream_twiml(voice_session_id)
        return Response(content=twiml, media_type="text/xml")
    except Exception as e:
        twilio_logger.error(f"Error handling inbound call webhook: {str(e)}")
        fallback_twiml = twilio_service.generate_hangup_twiml("क्षमा करें, हमारे सर्वर में तकनीकी समस्या है। कृपया कुछ समय बाद पुनः प्रयास करें।")
        return Response(content=fallback_twiml, media_type="text/xml")

@router.websocket("/stream/{voice_session_id}")
async def handle_voice_stream(websocket: WebSocket, voice_session_id: str, db: AsyncSession = Depends(get_db)):
    """Bidirectional WebSocket connection handling G.711 mu-law audio from Twilio and routing to Gemini Live WebSocket."""
    twilio_logger.info(f"WebSocket voice stream connection request for session: {voice_session_id}")
    await websocket.accept()

    # 1. Fetch Voice Session & Hospital ID
    session_stmt = select(VoiceSession).where(VoiceSession.id == voice_session_id)
    session = (await db.execute(session_stmt)).scalar_one_or_none()
    if not session:
        twilio_logger.error(f"Voice session {voice_session_id} not found. Terminating WebSocket.")
        await websocket.close()
        return

    call_stmt = select(CallLog).where(CallLog.id == session.call_log_id)
    call_log = (await db.execute(call_stmt)).scalar_one_or_none()
    hospital_id = call_log.hospital_id if call_log else "hosp_default"
    
    caller_number = call_log.caller_number if call_log else ""
    # Resolve the patient's phone number: if From is Twilio number (outbound), use receiver (To) number
    if call_log and call_log.caller_number == settings.TWILIO_PHONE_NUMBER:
        resolved_patient_phone = call_log.receiver_number
    else:
        resolved_patient_phone = caller_number

    # 2. Build default system instructions prompt for the voice model
    prompt_manager = PromptManager(db)
    system_instruction = await prompt_manager.compile_receptionist_prompt(
        hospital_id=hospital_id,
        caller_phone=resolved_patient_phone
    )

    # 3. Instantiate Gemini Live WebSocket Client
    gemini_client = GeminiLiveClient(system_instruction)
    try:
        await gemini_client.connect()
    except Exception as e:
        twilio_logger.error(f"Failed to connect to Gemini Live WebSocket: {str(e)}")
        await websocket.close()
        return

    stream_sid = None
    caller_phone = resolved_patient_phone  # resolved patient phone — used for patient auto-creation
    scheduling_engine = SchedulingEngine(db)
    appointment_engine = AppointmentEngine(db)

    last_activity_time = asyncio.get_event_loop().time()
    model_is_speaking = False
    turn_complete_time = None        # When AI last finished speaking
    silence_triggered = False        # Prevent repeated re-prompt spam
    booking_completed = False        # Flag to trigger call hangup after successful booking

    async def silence_monitor():
        nonlocal last_activity_time, model_is_speaking, stream_sid, turn_complete_time, booking_completed
        try:
            while True:
                await asyncio.sleep(0.5)  # Check every 0.5 second
                if booking_completed:
                    break  # Stop monitoring silence if booking is completed and call is hanging up
                if not stream_sid:
                    continue
                if model_is_speaking:
                    continue  # AI is still speaking, don't start timer
                if turn_complete_time is None:
                    continue  # AI hasn't spoken yet, don't start timer

                elapsed = asyncio.get_event_loop().time() - turn_complete_time
                if elapsed > 5.0:  # 5 seconds after AI finished speaking
                    twilio_logger.info("Caller silent for 5s after AI turn. Sending periodic re-prompt.")
                    # Reset the silence timer so it triggers again in another 5 seconds if silence continues
                    turn_complete_time = asyncio.get_event_loop().time()
                    await gemini_client.send_text_trigger(
                        "(मरीज़ शांत है, कृपया अपना पिछला सवाल बहुत संक्षेप में हिंदी में दोबारा दोहराएं।)"
                    )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            twilio_logger.error(f"Error in silence monitor task: {str(e)}")

    async def gemini_to_twilio_sender():
        """Listens for audio content and function calls coming from Gemini Live API and relays them to Twilio."""
        nonlocal stream_sid, last_activity_time, model_is_speaking, turn_complete_time, silence_triggered, booking_completed
        try:
            async for event in gemini_client.receive_stream():
                if not stream_sid:
                    continue

                if event["type"] == "audio":
                    model_is_speaking = True
                    silence_triggered = False   # User got a response, re-arm silence detection
                    last_activity_time = asyncio.get_event_loop().time()
                    # Decode/Resample Gemini 24kHz PCM to Twilio 8kHz G.711 mu-law
                    raw_pcm_24k = base64.b64decode(event["data"])
                    raw_pcm_8k = resample_pcm(raw_pcm_24k, from_rate=24000, to_rate=8000)
                    mulaw_data = pcm_to_ulaw(raw_pcm_8k)
                    base64_mulaw = base64.b64encode(mulaw_data).decode("utf-8")

                    # Dispatch media chunk to Twilio
                    response_frame = {
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {
                            "payload": base64_mulaw
                        }
                    }
                    await websocket.send_text(json.dumps(response_frame))

                elif event["type"] == "turn_complete":
                    model_is_speaking = False
                    turn_complete_time = asyncio.get_event_loop().time()  # Start silence timer NOW
                    
                    if booking_completed:
                        twilio_logger.info("Booking completed and model finished speaking. Scheduling call hangup in 4.5 seconds.")
                        async def hangup_after_delay():
                            await asyncio.sleep(4.5)  # Wait 4.5s for audio buffer to play completely
                            twilio_logger.info("Hanging up call after booking confirmation.")
                            if call_log and call_log.call_sid:
                                try:
                                    await twilio_service.terminate_call_async(call_log.call_sid)
                                except Exception as term_err:
                                    twilio_logger.error(f"Failed to terminate call SID {call_log.call_sid}: {str(term_err)}")
                            await websocket.close()
                        asyncio.create_task(hangup_after_delay())

                elif event["type"] == "interrupted":
                    # Handle VAD speech interruption: Clear Twilio's audio queue immediately
                    model_is_speaking = False
                    turn_complete_time = asyncio.get_event_loop().time()
                    twilio_logger.info("Caller interrupted AI speaker. Clearing Twilio playback buffer and resetting speaking states.")
                    clear_frame = {
                        "event": "clear",
                        "streamSid": stream_sid
                    }
                    await websocket.send_text(json.dumps(clear_frame))

                elif event["type"] == "function_call":
                    # Execute Gemini tool call
                    call_id = event["id"]
                    tool_name = event["name"]
                    args = event["args"]
                    twilio_logger.info(f"Gemini requested tool call: {tool_name} with arguments: {args}")
                    
                    result = {}
                    try:
                        if tool_name == "check_availability":
                            from datetime import date as date_type
                            raw_date = str(args["date"]).strip()
                            if "T" in raw_date:
                                raw_date = raw_date.split("T")[0]
                            elif " " in raw_date:
                                raw_date = raw_date.split(" ")[0]
                            target_date = date_type.fromisoformat(raw_date)
                            slots = await scheduling_engine.get_available_slots(args["doctor_id"], target_date)
                            # Return all available slots in readable HH:MM format
                            slot_times = [s.start_time.strftime("%I:%M %p") for s in slots]
                            result = {
                                "available_slots": slot_times,
                                "total_available": len(slots),
                                "date": args["date"]
                            }
                            twilio_logger.info(f"check_availability returned {len(slots)} slots for {args['doctor_id']} on {args['date']}")

                        elif tool_name == "book_appointment":
                            from datetime import date as date_type
                            raw_dt = args["appointment_datetime"].strip()
                            try:
                                if "AM" in raw_dt.upper() or "PM" in raw_dt.upper():
                                    appt_time = datetime.strptime(raw_dt.replace("T", " "), "%Y-%m-%d %I:%M %p")
                                else:
                                    if " " in raw_dt and "T" not in raw_dt:
                                        parts = raw_dt.split(" ")
                                        raw_dt = f"{parts[0]}T{parts[1]}"
                                    appt_time = datetime.fromisoformat(raw_dt)
                            except Exception:
                                from app.core.exceptions import ValidationException
                                raise ValidationException("कृपया अपॉइंटमेंट का समय सही से बताएं।")
                            patient_name_raw = args.get("patient_name", "Patient")
                            doctor_id = args["doctor_id"]

                            # Auto-find or create patient using caller's phone number AND name
                            patient = None
                            name_parts = patient_name_raw.strip().split(" ", 1)
                            first_name = name_parts[0]
                            last_name = name_parts[1] if len(name_parts) > 1 else ""

                            if caller_phone:
                                pt_stmt = select(Patient).where(
                                    Patient.hospital_id == hospital_id,
                                    Patient.phone == caller_phone,
                                    Patient.first_name == first_name,
                                    Patient.last_name == last_name
                                )
                                patient = (await db.execute(pt_stmt)).scalar_one_or_none()

                            if not patient:
                                # Create new patient record from call data
                                import uuid as _uuid
                                new_patient = Patient(
                                    id=str(_uuid.uuid4()),
                                    hospital_id=hospital_id,
                                    first_name=first_name,
                                    last_name=last_name,
                                    phone=caller_phone or "0000000000",
                                    date_of_birth=date_type(1990, 1, 1),  # placeholder DOB
                                    gender="Unknown"
                                )
                                db.add(new_patient)
                                await db.flush()
                                patient = new_patient
                                twilio_logger.info(f"Created new patient record for caller: {caller_phone} name: {patient_name_raw}")
                            else:
                                twilio_logger.info(f"Found existing patient: {patient.id} for phone: {caller_phone} name: {patient_name_raw}")

                            # Book the appointment
                            appt = await appointment_engine.book_appointment(
                                hospital_id=hospital_id,
                                patient_id=patient.id,
                                doctor_id=doctor_id,
                                appointment_datetime=appt_time,
                                reason=args.get("reason", "Voice Booking")
                            )

                            # Commit to DB so appointment is permanently saved
                            await db.commit()
                            booking_completed = True
                            twilio_logger.info(f"Appointment {appt.id} COMMITTED to database successfully.")

                            result = {
                                "status": "BOOKED",
                                "appointment_id": appt.id,
                                "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
                                "appointment_datetime": appt.appointment_datetime.isoformat()
                            }

                            # Fire n8n webhook asynchronously (non-blocking)
                            try:
                                from app.services.automation import AutomationService
                                automation = AutomationService()
                                doctor_stmt = select(Doctor).where(Doctor.id == doctor_id)
                                doctor = (await db.execute(doctor_stmt)).scalar_one_or_none()
                                webhook_details = {
                                    "appointment_id": appt.id,
                                    "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
                                    "patient_phone": patient.phone,
                                    "doctor_id": doctor_id,
                                    "doctor_name": f"Dr. {doctor.first_name} {doctor.last_name}" if doctor else "Doctor",
                                    "appointment_datetime": appt.appointment_datetime.isoformat(),
                                    "reason": appt.reason
                                }
                                asyncio.create_task(automation.dispatch_appointment_booked_webhook(webhook_details))
                            except Exception as auto_err:
                                twilio_logger.error(f"n8n webhook dispatch failed (non-critical): {str(auto_err)}")

                            # WhatsApp Notification — directly via Twilio (no n8n needed)
                            try:
                                from app.services.whatsapp import WhatsAppNotificationService
                                wa_service = WhatsAppNotificationService()
                                doctor_stmt2 = select(Doctor).where(Doctor.id == doctor_id)
                                doctor2 = (await db.execute(doctor_stmt2)).scalar_one_or_none()
                                wa_details = {
                                    "appointment_id": appt.id,
                                    "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
                                    "patient_phone": patient.phone,
                                    "doctor_name": f"Dr. {doctor2.first_name} {doctor2.last_name}" if doctor2 else "Doctor",
                                    "appointment_datetime": appt.appointment_datetime.isoformat(),
                                    "reason": appt.reason
                                }
                                # Patient ko bhi unki appointment details + payment link bhejo
                                asyncio.create_task(wa_service.send_patient_confirmation(wa_details))
                                twilio_logger.info("WhatsApp confirmation task queued for patient.")
                            except Exception as wa_err:
                                twilio_logger.error(f"WhatsApp notification dispatch failed (non-critical): {str(wa_err)}")

                        elif tool_name == "save_patient_intake":
                            from app.database.models.appointment import PatientIntake
                            intake_appt_id = args.get("appointment_id", "")
                            twilio_logger.info(f"Saving patient intake for appointment: {intake_appt_id}")

                            # Upsert intake record
                            existing_intake_stmt = select(PatientIntake).where(
                                PatientIntake.appointment_id == intake_appt_id
                            )
                            existing_intake = (await db.execute(existing_intake_stmt)).scalar_one_or_none()

                            if existing_intake:
                                existing_intake.has_visited_before = args.get("has_visited_before")
                                existing_intake.previous_doctor = args.get("previous_doctor")
                                existing_intake.has_reports = args.get("has_reports")
                                existing_intake.report_details = args.get("report_details")
                                existing_intake.current_medicines = args.get("current_medicines")
                                existing_intake.additional_notes = args.get("additional_notes")
                            else:
                                import uuid as _uuid2
                                new_intake = PatientIntake(
                                    id=str(_uuid2.uuid4()),
                                    appointment_id=intake_appt_id,
                                    has_visited_before=args.get("has_visited_before"),
                                    previous_doctor=args.get("previous_doctor"),
                                    has_reports=args.get("has_reports"),
                                    report_details=args.get("report_details"),
                                    current_medicines=args.get("current_medicines"),
                                    additional_notes=args.get("additional_notes")
                                )
                                db.add(new_intake)

                            await db.commit()
                            booking_completed = True  # Triggers call hangup after AI says goodbye
                            twilio_logger.info(f"Patient intake saved successfully for: {intake_appt_id}")
                            result = {"status": "SAVED", "appointment_id": intake_appt_id}

                        elif tool_name == "get_active_bookings":
                            from app.database.models.appointment import Appointment, Patient, Doctor, AppointmentStatusHistory
                            
                            twilio_logger.info(f"Fetching active bookings for caller phone: {resolved_patient_phone}")
                            stmt = (
                                select(Appointment, Patient, Doctor)
                                .join(Patient, Appointment.patient_id == Patient.id)
                                .join(Doctor, Appointment.doctor_id == Doctor.id)
                                .where(
                                    and_(
                                        Patient.phone == resolved_patient_phone,
                                        Appointment.status.in_(["SCHEDULED", "PENDING_PAYMENT", "RESCHEDULED"])
                                    )
                                )
                                .order_by(Appointment.appointment_datetime)
                            )
                            db_results = (await db.execute(stmt)).all()
                            
                            now = datetime.now()
                            bookings_list = []
                            for appt, patient, doctor in db_results:
                                # Fetch reschedule count from status history
                                history_stmt = select(AppointmentStatusHistory).where(
                                    and_(
                                        AppointmentStatusHistory.appointment_id == appt.id,
                                        AppointmentStatusHistory.new_status == "RESCHEDULED"
                                    )
                                )
                                reschedules = (await db.execute(history_stmt)).all()
                                reschedule_count = len(reschedules)
                                
                                created_at_dt = appt.created_at or appt.appointment_datetime
                                hours_since_booking = (now - created_at_dt).total_seconds() / 3600.0
                                is_within_2_days = hours_since_booking <= 48.0
                                
                                bookings_list.append({
                                    "appointment_id": appt.id,
                                    "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
                                    "doctor_name": f"Dr. {doctor.first_name} {doctor.last_name}",
                                    "doctor_id": doctor.id,
                                    "appointment_datetime": appt.appointment_datetime.strftime("%Y-%m-%d %I:%M %p"),
                                    "payment_status": appt.status,  # SCHEDULED = Paid, PENDING_PAYMENT = Unpaid
                                    "reschedule_count": reschedule_count,
                                    "is_within_2_days": is_within_2_days
                                })
                            
                            result = {"bookings": bookings_list, "total_active": len(bookings_list)}
                            twilio_logger.info(f"get_active_bookings returned {len(bookings_list)} active bookings.")

                        elif tool_name == "reschedule_appointment_by_ai":
                            from app.database.models.appointment import Appointment, Patient, Doctor, AppointmentStatusHistory
                            from app.services.whatsapp import WhatsAppNotificationService
                            
                            appt_id = args["appointment_id"]
                            new_dt_str = args["new_datetime"]
                            
                            twilio_logger.info(f"AI Rescheduling appt: {appt_id} to {new_dt_str}")
                            
                            # 1. Fetch appointment
                            stmt = select(Appointment).where(Appointment.id == appt_id)
                            appt = (await db.execute(stmt)).scalar_one_or_none()
                            if not appt:
                                result = {"status": "ERROR", "message": "Appointment not found"}
                            else:
                                old_status = appt.status
                                appt.status = "RESCHEDULED"
                                appt.appointment_datetime = datetime.fromisoformat(new_dt_str)
                                appt.updated_at = datetime.now()
                                
                                # 2. Add history log
                                history = AppointmentStatusHistory(
                                    id=str(uuid.uuid4()),
                                    appointment_id=appt.id,
                                    previous_status=old_status,
                                    new_status="RESCHEDULED",
                                    change_reason="Helpline AI voice reschedule"
                                )
                                db.add(history)
                                await db.flush()
                                
                                # 3. Fetch details for WhatsApp
                                pt_stmt = select(Patient).where(Patient.id == appt.patient_id)
                                patient = (await db.execute(pt_stmt)).scalar_one_or_none()
                                doc_stmt = select(Doctor).where(Doctor.id == appt.doctor_id)
                                doctor = (await db.execute(doc_stmt)).scalar_one_or_none()
                                
                                await db.commit()
                                
                                # 4. Send WhatsApp
                                if patient and doctor:
                                    wa_service = WhatsAppNotificationService()
                                    wa_details = {
                                        "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
                                        "patient_phone": patient.phone,
                                        "doctor_name": f"Dr. {doctor.first_name} {doctor.last_name}",
                                        "new_datetime": new_dt_str,
                                        "cutoff_note": "कृपया नए समय पर अस्पताल पहुँचे।"
                                    }
                                    asyncio.create_task(wa_service.send_reschedule_notification(wa_details))
                                
                                booking_completed = True  # Disconnect call cleanly
                                result = {"status": "RESCHEDULED", "appointment_id": appt_id}
                                twilio_logger.info(f"AI Rescheduled appointment {appt_id} successfully.")

                        else:
                            result = {"error": f"Tool '{tool_name}' not recognized."}

                    except Exception as err:
                        from app.core.exceptions import ValidationException
                        if isinstance(err, ValidationException):
                            friendly_msg = str(err)
                            err_lower = friendly_msg.lower()

                            if "already has an active appointment" in err_lower:
                                # Duplicate booking — tell Gemini clearly
                                result = {"error": "इस मरीज़ का इस डॉक्टर के साथ उस दिन के लिए पहले से एक अपॉइंटमेंट बुक है। कोई दूसरा दिन या डॉक्टर चुनें।"}

                            elif "not available for booking" in err_lower or "aaj ki taareekh" in err_lower or "आज की तारीख" in friendly_msg:
                                # Slot not free or today blocked — fetch real available slots and return them
                                try:
                                    from app.engines.scheduling import SchedulingEngine
                                    from datetime import date as _date, timedelta as _td
                                    sched_eng = SchedulingEngine(db)
                                    booked_doctor_id = args.get("doctor_id", "")
                                    # Try tomorrow first, then day after
                                    alt_slots = []
                                    for days_ahead in [1, 2]:
                                        alt_date = _date.today() + _td(days=days_ahead)
                                        alt_slots = await sched_eng.get_available_slots(booked_doctor_id, alt_date)
                                        if alt_slots:
                                            alt_date_label = alt_date.strftime("%d %B %Y")
                                            slot_times = [s.start_time.strftime("%I:%M %p") for s in alt_slots]
                                            result = {
                                                "error": f"वह समय उपलब्ध नहीं है।",
                                                "suggestion": f"{alt_date_label} को ये स्लॉट उपलब्ध हैं: {', '.join(slot_times[:10])}. कृपया इनमें से कोई समय चुनें।",
                                                "available_date": alt_date.isoformat(),
                                                "available_slots": slot_times[:10]
                                            }
                                            break
                                    if not alt_slots:
                                        result = {"error": "अगले 2 दिनों में कोई भी स्लॉट उपलब्ध नहीं है। कृपया बाद में कॉल करें।"}
                                except Exception as slot_err:
                                    twilio_logger.error(f"Failed to fetch alt slots: {slot_err}")
                                    result = {"error": "वह समय उपलब्ध नहीं है। कोई दूसरा समय बताइए।"}
                            else:
                                result = {"error": friendly_msg}

                            twilio_logger.warning(f"Validation error in tool {tool_name}: {friendly_msg}")
                        else:
                            twilio_logger.error(f"Error executing tool {tool_name}: {str(err)}", exc_info=True)
                            result = {"error": str(err)}

                    await gemini_client.send_tool_response(call_id, tool_name, result)
        except Exception as e:
            twilio_logger.error(f"Error in Gemini to Twilio sender loop: {str(e)}") 

    # Run the sender and silence monitor loops as concurrent background tasks
    sender_task = asyncio.create_task(gemini_to_twilio_sender())
    silence_task = asyncio.create_task(silence_monitor())

    try:
        while True:
            message_text = await websocket.receive_text()
            data = json.loads(message_text)

            event = data.get("event")
            if event == "start":
                stream_sid = data["start"]["streamSid"]
                twilio_logger.info(f"Twilio stream connected. Stream SID: {stream_sid}")
                # Trigger the model: give EXACTLY the opening greeting — just ask for name
                await gemini_client.send_text_trigger(
                    "[SYSTEM] The call has just connected. Start the conversation now. "
                    "Greet the patient warmly as CP Tiwari Hospital's appointment assistant. "
                    "Ask ONLY for their full name. Nothing else."
                )
            
            elif event == "media":
                if not stream_sid:
                    continue
                
                 # Retrieve and decode Twilio G.711 mu-law audio
                payload = data["media"]["payload"]
                raw_mulaw = base64.b64decode(payload)
                raw_pcm_8k = ulaw_to_pcm(raw_mulaw)

                # Resample Twilio 8kHz PCM to Gemini 16kHz PCM
                raw_pcm_16k = resample_pcm(raw_pcm_8k, from_rate=8000, to_rate=16000)
                base64_pcm_16k = base64.b64encode(raw_pcm_16k).decode("utf-8")

                # Calculate volume amplitude to distinguish speech from silence
                amplitude = calculate_amplitude(raw_pcm_8k)

                # Reset silence tracking only when user is actively speaking (amplitude > 250)
                if not model_is_speaking and amplitude > 250:
                    turn_complete_time = None   # User speaking — reset silence clock

                # Forward base64 PCM audio chunk to Gemini only if the AI is not speaking
                if not model_is_speaking:
                    await gemini_client.send_audio_chunk(base64_pcm_16k)
            
            elif event == "stop":
                twilio_logger.info(f"Twilio stream stopped for session: {voice_session_id}")
                break
            
    except WebSocketDisconnect:
        twilio_logger.info(f"WebSocket disconnected for session: {voice_session_id}")
    except Exception as e:
        twilio_logger.error(f"WebSocket error in session {voice_session_id}: {str(e)}")
    finally:
        # Cancel the sender and silence tasks
        sender_task.cancel()
        silence_task.cancel()
        # Close connection to Gemini Live WebSocket
        await gemini_client.close()

        # Update voice session to TERMINATED in DB
        await db.execute(
            update(VoiceSession)
            .where(VoiceSession.id == voice_session_id)
            .values(session_status="TERMINATED", updated_at=datetime.now(timezone.utc))
        )

        # Log incomplete call — if session ended but no appointment was booked this call
        # (appointment_engine.book_appointment sets a DB record; we just log a warning here)
        try:
            from sqlalchemy import select as sa_select
            from app.database.models.appointment import Appointment
            recent_appt_stmt = sa_select(Appointment).where(
                Appointment.hospital_id == hospital_id
            ).order_by(Appointment.created_at.desc()).limit(1)
            recent_appt = (await db.execute(recent_appt_stmt)).scalar_one_or_none()
            # Just log — no automated action for now
            twilio_logger.info(
                f"Call session {voice_session_id} ended. Caller: {caller_phone}. "
                f"If no appointment booked, this was an incomplete/dropped call."
            )
        except Exception:
            pass

        await db.commit()


class TestCallRequest(BaseModel):
    to_number: Optional[str] = Field(None, description="The target phone number to call. Falls back to TEST_PHONE_NUMBER from environment/env if omitted.")


class TestCallResponse(BaseModel):
    success: bool
    call_sid: str
    message: str


@router.post("/test-call", response_model=TestCallResponse)
async def initiate_test_call(request: TestCallRequest):
    """Initiates a test call using Twilio API to the specified phone number."""
    # Resolve recipient phone number
    to_number = request.to_number or settings.TEST_PHONE_NUMBER
    if not to_number:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recipient phone number must be provided in the request body (to_number) or configured as TEST_PHONE_NUMBER in environment variables."
        )

    # Validate that webhook url is configured
    if not settings.TWILIO_WEBHOOK_URL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TWILIO_WEBHOOK_URL environment variable is missing or empty."
        )

    try:
        call_sid = await twilio_service.initiate_outbound_call_async(
            to_number=to_number,
            webhook_domain=settings.TWILIO_WEBHOOK_URL
        )
        return TestCallResponse(
            success=True,
            call_sid=call_sid,
            message="Call initiated successfully"
        )
    except Exception as e:
        twilio_logger.error(f"Failed to trigger test call: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Twilio Call execution failed: {str(e)}"
        )

