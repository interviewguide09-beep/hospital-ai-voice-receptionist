from datetime import datetime, date, time, timedelta
from typing import List
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models.appointment import Doctor, DoctorSchedule, DoctorLeave, HospitalHoliday, WorkingHour, Appointment
from app.core.logging import engine_logger
from app.schemas.appointment import AvailableSlot

class SchedulingEngine:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def get_available_slots(self, doctor_id: str, search_date: date, ignore_limits: bool = False) -> List[AvailableSlot]:
        """Calculates and returns available scheduling slots for a specific doctor on a given date, checking holidays, working hours, leaves, and existing bookings."""
        engine_logger.info(f"Calculating slots for doctor {doctor_id} on {search_date} (ignore_limits={ignore_limits})")
        
        # 1. Fetch Doctor and Hospital ID
        doctor_stmt = select(Doctor).where(Doctor.id == doctor_id, Doctor.is_active == True)
        doctor_result = (await self.db.execute(doctor_stmt)).scalar_one_or_none()
        if not doctor_result:
            engine_logger.warning(f"Doctor {doctor_id} not found or inactive.")
            return []
        
        # 1.5 Enforce blocking today's bookings and bookings beyond 2 days (only allow tomorrow and onwards up to 2 days)
        if not ignore_limits:
            today = date.today()
            if search_date <= today:
                engine_logger.info(f"Blocking slot generation for today or past date: {search_date}")
                return []
            if search_date > today + timedelta(days=2):
                engine_logger.info(f"Blocking slot generation beyond 2 days: {search_date}")
                return []
            
            
        hospital_id = doctor_result.hospital_id

        # 2. Check if the date is a Hospital Holiday
        holiday_stmt = select(HospitalHoliday).where(
            and_(
                HospitalHoliday.hospital_id == hospital_id,
                HospitalHoliday.holiday_date == search_date
            )
        )
        holiday_result = (await self.db.execute(holiday_stmt)).scalar_one_or_none()
        if holiday_result:
            engine_logger.info(f"Selected date {search_date} is a hospital holiday: {holiday_result.name}.")
            return []

        # 3. Check hospital Working Hours
        day_of_week = search_date.isoweekday()  # 1=Monday, 7=Sunday
        wh_stmt = select(WorkingHour).where(
            and_(
                WorkingHour.hospital_id == hospital_id,
                WorkingHour.day_of_week == day_of_week
            )
        )
        wh = (await self.db.execute(wh_stmt)).scalar_one_or_none()
        if not wh or wh.is_closed:
            engine_logger.info(f"Hospital is closed on weekday {day_of_week} ({search_date}).")
            return []

        # 4. Check if Doctor is on Leave
        leave_stmt = select(DoctorLeave).where(
            and_(
                DoctorLeave.doctor_id == doctor_id,
                DoctorLeave.start_date <= search_date,
                DoctorLeave.end_date >= search_date
            )
        )
        leave_result = (await self.db.execute(leave_stmt)).scalar_one_or_none()
        if leave_result:
            engine_logger.info(f"Doctor {doctor_id} is on leave on {search_date}. Reason: {leave_result.reason}")
            return []

        # 5. Fetch Doctor's Standard weekly schedule for this weekday
        sched_stmt = select(DoctorSchedule).where(
            and_(
                DoctorSchedule.doctor_id == doctor_id,
                DoctorSchedule.day_of_week == day_of_week
            )
        )
        schedules = (await self.db.execute(sched_stmt)).scalars().all()
        if not schedules:
            engine_logger.info(f"Doctor {doctor_id} has no schedule configured for weekday {day_of_week}.")
            return []

        # 6. Fetch Existing bookings for this doctor on this day
        start_datetime = datetime.combine(search_date, time.min)
        end_datetime = datetime.combine(search_date, time.max)
        
        appt_stmt = select(Appointment).where(
            and_(
                Appointment.doctor_id == doctor_id,
                Appointment.appointment_datetime >= start_datetime,
                Appointment.appointment_datetime <= end_datetime,
                Appointment.status.in_(["SCHEDULED", "PENDING_PAYMENT"])
            )
        )
        booked_appointments = (await self.db.execute(appt_stmt)).scalars().all()
        booked_times = {appt.appointment_datetime.time() for appt in booked_appointments}

        # 7. Generate Slots
        available_slots: List[AvailableSlot] = []
        for schedule in schedules:
            if not schedule.slot_duration_minutes or schedule.slot_duration_minutes <= 0:
                engine_logger.error(f"Doctor schedule {schedule.id} has invalid slot duration: {schedule.slot_duration_minutes}. Skipping to prevent infinite loop.")
                continue
            slot_duration = timedelta(minutes=schedule.slot_duration_minutes)
            current_time = datetime.combine(search_date, schedule.start_time)
            end_time_limit = datetime.combine(search_date, schedule.end_time)

            while current_time + slot_duration <= end_time_limit:
                slot_time = current_time.time()
                
                # Verify that the slot is within hospital opening hours
                if wh.open_time <= slot_time < wh.close_time:
                    # Check if the slot overlaps with existing appointments
                    if slot_time not in booked_times:
                        available_slots.append(AvailableSlot(
                            doctor_id=doctor_id,
                            date=search_date,
                            start_time=slot_time,
                            end_time=(current_time + slot_duration).time()
                        ))
                
                current_time += slot_duration

        engine_logger.info(f"Generated {len(available_slots)} available slots for doctor {doctor_id} on {search_date}")
        return available_slots
