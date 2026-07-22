import os
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database.session import get_db
from app.database.models.appointment import Patient, Appointment, Doctor, Hospital
from app.database.models.conversation import CallLog, VoiceSession

router = APIRouter()

@router.get("/logs")
async def get_logs(lines: int = 200):
    log_path = "logs/hospital_voice_receptionist.log"
    if not os.path.exists(log_path):
        return {"error": "Log file not found."}
    
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
        return {
            "total_lines": len(all_lines),
            "requested_lines": lines,
            "logs": all_lines[-lines:]
        }
    except Exception as e:
        return {"error": f"Failed to read logs: {str(e)}"}

@router.get("/db")
async def get_db_info(db: AsyncSession = Depends(get_db)):
    try:
        # Hospitals
        hosps = (await db.execute(select(Hospital))).scalars().all()
        hosp_list = [{"id": h.id, "name": h.name, "phone": h.phone} for h in hosps]

        # Doctors
        docs = (await db.execute(select(Doctor))).scalars().all()
        doc_list = [{"id": d.id, "name": f"Dr. {d.first_name} {d.last_name}", "active": d.is_active, "dept": d.department_id} for d in docs]

        # Recent Patients
        pats = (await db.execute(select(Patient).order_by(Patient.created_at.desc()).limit(20))).scalars().all()
        pat_list = [{"id": p.id, "name": f"{p.first_name} {p.last_name}", "phone": p.phone, "created_at": p.created_at.isoformat()} for p in pats]

        # Recent Appointments
        appts = (await db.execute(select(Appointment).order_by(Appointment.created_at.desc()).limit(20))).scalars().all()
        appt_list = [
            {
                "id": a.id,
                "patient_id": a.patient_id,
                "doctor_id": a.doctor_id,
                "datetime": a.appointment_datetime.isoformat(),
                "status": a.status,
                "created_at": a.created_at.isoformat()
            }
            for a in appts
        ]

        # Recent Calls
        calls = (await db.execute(select(CallLog).order_by(CallLog.created_at.desc()).limit(20))).scalars().all()
        call_list = [
            {
                "id": c.id,
                "caller_number": c.caller_number,
                "status": c.call_status,
                "created_at": c.created_at.isoformat()
            }
            for c in calls
        ]

        return {
            "hospitals": hosp_list,
            "doctors": doc_list,
            "recent_patients": pat_list,
            "recent_appointments": appt_list,
            "recent_calls": call_list
        }
    except Exception as e:
        import traceback
        return {"error": f"Database query failed: {str(e)}", "traceback": traceback.format_exc()}

@router.get("/clear")
async def clear_logs():
    log_path = "logs/hospital_voice_receptionist.log"
    try:
        if os.path.exists(log_path):
            with open(log_path, "w", encoding="utf-8") as f:
                f.truncate(0)
            return {"message": "Logs cleared successfully."}
        return {"message": "Log file did not exist."}
    except Exception as e:
        return {"error": f"Failed to clear logs: {str(e)}"}
