import asyncio
from sqlalchemy import select
from app.database.session import async_session_factory
from app.database.base import Base  # Crucial to register all models!
from app.database.models.appointment import Appointment, Patient, Doctor

async def check_appointments():
    print("Checking appointments in DB...")
    async with async_session_factory() as db:
        try:
            # Check Patients
            pt_stmt = select(Patient)
            patients = (await db.execute(pt_stmt)).scalars().all()
            print(f"Total Patients: {len(patients)}")
            for p in patients:
                # Safe print
                name = f"{p.first_name} {p.last_name}".encode('ascii', errors='ignore').decode('ascii')
                print(f"Patient: ID={p.id}, Name={name}, Phone={p.phone}")
            
            # Check Appointments
            appt_stmt = select(Appointment)
            appts = (await db.execute(appt_stmt)).scalars().all()
            print(f"Total Appointments: {len(appts)}")
            for a in appts:
                print(f"Appointment: ID={a.id}, Doctor={a.doctor_id}, Patient={a.patient_id}, DateTime={a.appointment_datetime}, Status={a.status}")
        except Exception as e:
            print(f"Error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(check_appointments())
