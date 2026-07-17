import uuid
from datetime import datetime
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models.appointment import Appointment, AppointmentStatusHistory, Patient, Doctor
from app.engines.scheduling import SchedulingEngine
from app.core.exceptions import ValidationException, NotFoundException
from app.core.logging import engine_logger
from app.schemas.appointment import AppointmentRead

class AppointmentEngine:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.scheduling = SchedulingEngine(db_session)

    async def book_appointment(
        self,
        hospital_id: str,
        patient_id: str,
        doctor_id: str,
        appointment_datetime: datetime,
        reason: str = "Consultation",
        ignore_limits: bool = False
    ) -> AppointmentRead:
        """Books an appointment, validating slot availability and updating the database."""
        engine_logger.info(f"Attempting booking for patient {patient_id} with doctor {doctor_id} at {appointment_datetime} (ignore_limits={ignore_limits})")

        # 0.5 Enforce blocking today's bookings and bookings beyond 2 days (only allow tomorrow and onwards up to 2 days)
        if not ignore_limits:
            from datetime import date as date_type, timedelta
            appt_date = appointment_datetime.date()
            today = date_type.today()
            if appt_date <= today:
                raise ValidationException("Same day के लिए कॉल से अपॉइंटमेंट बुक नहीं होती।")
            if appt_date > today + timedelta(days=2):
                raise ValidationException("2 दिन के आगे की अपॉइंटमेंट बुक नहीं कर सकते।")

        # 1. Verify Patient Exists
        patient_stmt = select(Patient).where(Patient.id == patient_id)
        patient = (await self.db.execute(patient_stmt)).scalar_one_or_none()
        if not patient:
            raise NotFoundException(f"Patient with ID {patient_id} does not exist.")

        # 2. Verify Doctor Exists
        doctor_stmt = select(Doctor).where(Doctor.id == doctor_id, Doctor.is_active == True)
        doctor = (await self.db.execute(doctor_stmt)).scalar_one_or_none()
        if not doctor:
            raise NotFoundException(f"Doctor with ID {doctor_id} does not exist or is inactive.")

        # 2.5 Prevent duplicate bookings for same patient/doctor on same day
        from sqlalchemy import and_
        from datetime import time
        search_date = appointment_datetime.date()
        start_datetime = datetime.combine(search_date, time.min)
        end_datetime = datetime.combine(search_date, time.max)
        existing_stmt = select(Appointment).where(
            and_(
                Appointment.patient_id == patient_id,
                Appointment.doctor_id == doctor_id,
                Appointment.appointment_datetime >= start_datetime,
                Appointment.appointment_datetime <= end_datetime,
                Appointment.status.in_(["SCHEDULED", "PENDING_PAYMENT"])
            )
        )
        existing_appt = (await self.db.execute(existing_stmt)).scalars().first()
        if existing_appt:
            raise ValidationException(
                f"Patient already has an active appointment booked with this doctor on {search_date}."
            )
        

        # 3. Verify Slot Availability
        search_date = appointment_datetime.date()
        target_time = appointment_datetime.time()
        
        available_slots = await self.scheduling.get_available_slots(doctor_id, search_date, ignore_limits=ignore_limits)
        slot_is_free = False
        for slot in available_slots:
            if slot.start_time == target_time:
                slot_is_free = True
                break

        if not slot_is_free:
            raise ValidationException(f"The requested time slot {target_time} on {search_date} is not available for booking.")
        

        # 4. Create Appointment Record
        appointment_id = str(uuid.uuid4())
        appointment = Appointment(
            id=appointment_id,
            hospital_id=hospital_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            appointment_datetime=appointment_datetime,
            duration_minutes=30,
            status="PENDING_PAYMENT",
            reason=reason,
            source="VOICE"
        )
        self.db.add(appointment)

        # 5. Create Status History Record
        status_history = AppointmentStatusHistory(
            id=str(uuid.uuid4()),
            appointment_id=appointment_id,
            previous_status=None,
            new_status="PENDING_PAYMENT",
            change_reason="Initial booking via Voice Receptionist"
        )
        self.db.add(status_history)

        # 6. Flush changes (get transaction references ready)
        await self.db.flush()
        await self.db.refresh(appointment)
        engine_logger.info(f"Appointment {appointment_id} successfully booked.")
        
        return AppointmentRead.model_validate(appointment)

    async def cancel_appointment(self, appointment_id: str, reason: str = "Cancelled by patient via Voice") -> AppointmentRead:
        """Cancels an existing appointment, updating status history."""
        engine_logger.info(f"Cancelling appointment: {appointment_id}")
        
        # 1. Fetch Appointment
        stmt = select(Appointment).where(Appointment.id == appointment_id)
        appointment = (await self.db.execute(stmt)).scalar_one_or_none()
        if not appointment:
            raise NotFoundException(f"Appointment {appointment_id} not found.")

        if appointment.status == "CANCELLED":
            raise ValidationException("Appointment is already cancelled.")

        # 2. Record Status Change
        status_history = AppointmentStatusHistory(
            id=str(uuid.uuid4()),
            appointment_id=appointment_id,
            previous_status=appointment.status,
            new_status="CANCELLED",
            change_reason=reason
        )
        self.db.add(status_history)

        # 3. Update Status
        appointment.status = "CANCELLED"
        await self.db.flush()
        await self.db.refresh(appointment)
        
        engine_logger.info(f"Appointment {appointment_id} marked as CANCELLED.")
        return AppointmentRead.model_validate(appointment)

    async def reschedule_appointment(self, appointment_id: str, new_datetime: datetime) -> AppointmentRead:
        """Reschedules an existing appointment to a new available datetime slot."""
        engine_logger.info(f"Rescheduling appointment {appointment_id} to {new_datetime}")

        # 1. Fetch Appointment
        stmt = select(Appointment).where(Appointment.id == appointment_id)
        appointment = (await self.db.execute(stmt)).scalar_one_or_none()
        if not appointment:
            raise NotFoundException(f"Appointment {appointment_id} not found.")

        # 2. Verify Availability for the new slot
        search_date = new_datetime.date()
        target_time = new_datetime.time()
        
        available_slots = await self.scheduling.get_available_slots(appointment.doctor_id, search_date)
        slot_is_free = False
        for slot in available_slots:
            if slot.start_time == target_time:
                slot_is_free = True
                break

        if not slot_is_free:
            raise ValidationException(f"The new requested time slot {target_time} on {search_date} is not available.")

        # 3. Record Status Change
        status_history = AppointmentStatusHistory(
            id=str(uuid.uuid4()),
            appointment_id=appointment_id,
            previous_status=appointment.status,
            new_status="SCHEDULED",
            change_reason="Rescheduled via Voice Receptionist"
        )
        self.db.add(status_history)

        # 4. Update Datetime
        appointment.appointment_datetime = new_datetime
        await self.db.flush()
        await self.db.refresh(appointment)
        
        engine_logger.info(f"Appointment {appointment_id} rescheduled to {new_datetime}.")
        return AppointmentRead.model_validate(appointment)
