from datetime import date, datetime, timezone, timedelta
from typing import List, Optional
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import HTMLResponse
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.session import get_db
from app.core.dependencies import create_access_token, verify_password, get_current_user, hash_password
from app.database.models.call_log import User
from app.database.models.appointment import Doctor, Patient, Hospital, Department, Appointment
from app.engines.appointment import AppointmentEngine
from app.engines.scheduling import SchedulingEngine
from app.schemas.appointment import (
    AppointmentCreate, AppointmentRead, AppointmentUpdate,
    DoctorCreate, DoctorRead, PatientCreate, PatientRead,
    AvailableSlotsResponse, SlotQuery
)

router = APIRouter()


# ==========================================
# AUTHENTICATION ROUTE
# ==========================================

@router.post("/auth/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    """Authenticates admin console users and yields secure JWT tokens."""
    stmt = select(User).where(User.username == form_data.username, User.is_active == True)
    user = (await db.execute(stmt)).scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.password_hash):
        user_count_stmt = select(User)
        users_exist = (await db.execute(user_count_stmt)).scalars().all()
        if not users_exist and form_data.username == "admin":
            new_admin = User(
                id="usr_admin",
                username="admin",
                email="admin@hospital.com",
                password_hash=hash_password(form_data.password),
                is_active=True
            )
            db.add(new_admin)
            await db.commit()
            access_token = create_access_token(data={"sub": "admin"})
            return {"access_token": access_token, "token_type": "bearer"}

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}


# ==========================================
# APPOINTMENT MANAGEMENT
# ==========================================

@router.post("/appointments", response_model=AppointmentRead)
async def create_appointment(
    payload: AppointmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Creates a new patient booking, verifying slots availability."""
    engine = AppointmentEngine(db)
    return await engine.book_appointment(
        hospital_id=payload.hospital_id,
        patient_id=payload.patient_id,
        doctor_id=payload.doctor_id,
        appointment_datetime=payload.appointment_datetime,
        reason=payload.reason or "General Consultation"
    )


@router.delete("/appointments/{appointment_id}", response_model=AppointmentRead)
async def cancel_appointment(
    appointment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cancels an existing appointment."""
    engine = AppointmentEngine(db)
    return await engine.cancel_appointment(appointment_id)


@router.get("/appointments/availability", response_model=AvailableSlotsResponse)
async def get_doctor_availability(
    doctor_id: str,
    target_date: date,
    db: AsyncSession = Depends(get_db)
):
    """Public query endpoint to fetch free booking slots for a specific doctor."""
    scheduler = SchedulingEngine(db)
    slots = await scheduler.get_available_slots(doctor_id, target_date)
    return AvailableSlotsResponse(doctor_id=doctor_id, slots=slots)


# ==========================================
# DOCTORS MANAGEMENT
# ==========================================

@router.post("/doctors", response_model=DoctorRead)
async def create_doctor(
    payload: DoctorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Registers a new doctor profile under the clinical network."""
    import uuid
    from app.database.models.appointment import DoctorSpecialization

    doc_id = str(uuid.uuid4())
    doctor = Doctor(
        id=doc_id,
        hospital_id=payload.hospital_id,
        department_id=payload.department_id,
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=payload.email,
        phone=payload.phone,
        license_number=payload.license_number,
        is_active=True
    )
    db.add(doctor)

    for spec in payload.specializations:
        from app.database.models.appointment import DoctorSpecialization
        spec_row = DoctorSpecialization(
            id=str(uuid.uuid4()),
            doctor_id=doc_id,
            specialization=spec
        )
        db.add(spec_row)

    await db.commit()
    return doctor


@router.get("/doctors", response_model=List[DoctorRead])
async def list_doctors(db: AsyncSession = Depends(get_db)):
    """Retrieves all active doctor listings."""
    stmt = select(Doctor).where(Doctor.is_active == True)
    doctors = (await db.execute(stmt)).scalars().all()
    return doctors


# ==========================================
# PATIENTS MANAGEMENT
# ==========================================

@router.post("/patients", response_model=PatientRead)
async def register_patient(
    payload: PatientCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Registers a new patient file in the central medical records database."""
    import uuid
    pat_id = str(uuid.uuid4())
    patient = Patient(
        id=pat_id,
        hospital_id=payload.hospital_id,
        first_name=payload.first_name,
        last_name=payload.last_name,
        date_of_birth=payload.date_of_birth,
        gender=payload.gender,
        phone=payload.phone,
        email=payload.email,
        insurance_provider_id=payload.insurance_provider_id,
        insurance_policy_number=payload.insurance_policy_number
    )
    db.add(patient)
    await db.commit()
    return patient


# ==========================================
# RECEPTIONIST SCHEDULE DASHBOARD (No Auth Required)
# Open in browser: http://your-server/receptionist/schedule
# ==========================================

@router.get("/receptionist/schedule", response_class=HTMLResponse, tags=["receptionist"])
async def receptionist_today_schedule(
    date_str: Optional[str] = Query(None, description="Date in YYYY-MM-DD format. Defaults to today."),
    hospital_id: str = Query("hosp_default"),
    db: AsyncSession = Depends(get_db)
):
    """
    Human receptionist dashboard — shows all appointments for a given date organized by doctor.
    No authentication required. Auto-refreshes every 30 seconds.
    """
    if date_str:
        try:
            target_date = date.fromisoformat(date_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    else:
        target_date = date.today()

    start_dt = datetime.combine(target_date, datetime.min.time())
    end_dt = datetime.combine(target_date, datetime.max.time())

    appt_stmt = (
        select(Appointment, Patient, Doctor, Department)
        .join(Patient, Appointment.patient_id == Patient.id)
        .join(Doctor, Appointment.doctor_id == Doctor.id)
        .join(Department, Doctor.department_id == Department.id)
        .where(
            and_(
                Appointment.hospital_id == hospital_id,
                Appointment.appointment_datetime >= start_dt,
                Appointment.appointment_datetime <= end_dt,
                Appointment.status.in_(["SCHEDULED", "PENDING_PAYMENT"])
            )
        )
        .order_by(Doctor.first_name, Appointment.appointment_datetime)
    )
    results = (await db.execute(appt_stmt)).all()

    hosp_stmt = select(Hospital).where(Hospital.id == hospital_id)
    hospital_obj = (await db.execute(hosp_stmt)).scalar_one_or_none()
    hosp_name = hospital_obj.name if hospital_obj else "CP Tiwari Hospital"

    # Fetch active doctors and calculate their free slots
    docs_stmt = (
        select(Doctor, Department)
        .join(Department, Doctor.department_id == Department.id)
        .where(Doctor.is_active == True)
    )
    doctors_db = (await db.execute(docs_stmt)).all()
    
    scheduler = SchedulingEngine(db)
    doctors_info = []
    
    for doc, dept in doctors_db:
        free_slots = await scheduler.get_available_slots(doc.id, target_date)
        fees_map = {"doc_ortho": "₹500", "doc_cardio": "₹800", "doc_eye": "₹400"}
        fees = fees_map.get(doc.id, "₹500")
        
        # Timing representation in Hindi
        timing_str = "सोम–शुक्र, 10 AM - 1 PM | 2 PM - 5 PM"
        
        doctors_info.append({
            "name": f"Dr. {doc.first_name} {doc.last_name}",
            "dept": dept.name,
            "fees": fees,
            "timings": timing_str,
            "free_slots_count": len(free_slots)
        })

    by_doctor: dict = defaultdict(list)
    for appt, patient, doctor, dept in results:
        key = (f"Dr. {doctor.first_name} {doctor.last_name}", dept.name)
        by_doctor[key].append({
            "time": appt.appointment_datetime.strftime("%I:%M %p"),
            "time_24": appt.appointment_datetime.strftime("%H:%M"),
            "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
            "patient_phone": patient.phone,
            "reason": appt.reason or "—",
            "status": appt.status,
        })

    day_display = target_date.strftime("%d %B %Y")
    day_name = target_date.strftime("%A")
    prev_date = (target_date - timedelta(days=1)).isoformat()
    next_date = (target_date + timedelta(days=1)).isoformat()
    total = len(results)
    confirmed = sum(1 for appt, *_ in results if appt.status == "SCHEDULED")
    pending = total - confirmed
    is_today = (target_date == date.today())
    now_str = datetime.now().strftime("%I:%M:%S %p")

    dept_icons = {
        "Orthopedics": "🦴", "Cardiology": "❤️", "Ophthalmology": "👁️",
        "Heart": "❤️", "Eye": "👁️", "Haddi": "🦴",
    }

    doctor_sections = ""
    if not by_doctor:
        doctor_sections = """
        <div class="empty-card">
            <div class="empty-icon">📅</div>
            <h3>इस दिन कोई अपॉइंटमेंट नहीं है</h3>
            <p>अभी तक कोई बुकिंग नहीं आई है। जैसे ही AI Receptionist call लेगी, यहाँ दिखेगी।</p>
        </div>"""
    else:
        for (doc_name, dept_name), appts in by_doctor.items():
            icon = next((v for k, v in dept_icons.items() if k.lower() in dept_name.lower()), "👨‍⚕️")
            rows = ""
            for i, a in enumerate(appts, 1):
                is_scheduled = a["status"] == "SCHEDULED"
                badge = (
                    '<span class="badge confirmed">✅ Confirmed</span>' if is_scheduled
                    else '<span class="badge pending-pay">⏳ Payment Pending</span>'
                )
                rows += f"""
                <tr class="appt-row">
                    <td class="td-sno">{i}</td>
                    <td class="td-time">
                        <span class="time-pill">{a["time"]}</span>
                    </td>
                    <td class="td-patient">
                        <div class="patient-name">{a["patient_name"]}</div>
                    </td>
                    <td class="td-phone">
                        <a href="tel:{a["patient_phone"]}" class="phone-link">📞 {a["patient_phone"]}</a>
                    </td>
                    <td class="td-reason">{a["reason"]}</td>
                    <td class="td-status">{badge}</td>
                </tr>"""
            doctor_sections += f"""
            <div class="doctor-card">
                <div class="doctor-header">
                    <div class="doctor-left">
                        <div class="doc-icon">{icon}</div>
                        <div class="doc-details">
                            <div class="doc-name">{doc_name}</div>
                            <div class="doc-dept">{dept_name}</div>
                        </div>
                    </div>
                    <div class="doc-right">
                        <div class="doc-count">{len(appts)}</div>
                        <div class="doc-count-label">अपॉइंटमेंट</div>
                    </div>
                </div>
                <div class="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>⏰ समय</th>
                                <th>👤 मरीज़ का नाम</th>
                                <th>📞 मोबाइल</th>
                                <th>🩺 समस्या</th>
                                <th>स्थिति</th>
                            </tr>
                        </thead>
                        <tbody>{rows}</tbody>
                    </table>
                </div>
            </div>"""

    # Build the Sidebar Doctors Timings & Availability HTML
    sidebar_html = ""
    for d in doctors_info:
        badge_class = "slots-badge" if d["free_slots_count"] > 0 else "slots-badge empty"
        badge_text = f"{d['free_slots_count']} slots free" if d["free_slots_count"] > 0 else "Full / Closed"
        sidebar_html += f"""
        <div class="sidebar-doc-item">
            <div class="sidebar-doc-name">{d["name"]}</div>
            <div class="sidebar-doc-dept">{d["dept"]}</div>
            <div class="sidebar-doc-detail">
                <span>⏰ Timing:</span>
                <span>{d["timings"]}</span>
            </div>
            <div class="sidebar-doc-detail">
                <span>💰 OPD Fees:</span>
                <span>{d["fees"]}</span>
            </div>
            <div class="sidebar-doc-detail" style="margin-top: 8px;">
                <span>📅 Slots status:</span>
                <span class="{badge_class}">{badge_text}</span>
            </div>
        </div>"""

    today_flag = '<span class="today-badge">आज</span>' if is_today else ""

    html = f"""<!DOCTYPE html>
<html lang="hi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{hosp_name} — रिसेप्शनिस्ट डैशबोर्ड</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {{
            --primary: #1a4fa0;
            --primary-dark: #0f3276;
            --primary-light: #dbeafe;
            --accent: #0ea5e9;
            --green: #16a34a;
            --green-bg: #dcfce7;
            --yellow: #b45309;
            --yellow-bg: #fef9c3;
            --bg: #f0f5fc;
            --card-bg: #ffffff;
            --text: #0f172a;
            --text-muted: #64748b;
            --border: #e2e8f0;
            --shadow: 0 4px 20px rgba(26,79,160,0.10);
            --radius: 16px;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Inter', system-ui, sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
        }}

        /* ── HEADER ── */
        .header {{
            background: linear-gradient(135deg, #0f3276 0%, #1a4fa0 50%, #1e6cc4 100%);
            padding: 0;
            box-shadow: 0 4px 24px rgba(15,50,118,0.35);
        }}
        .header-inner {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 18px 28px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            flex-wrap: wrap;
        }}
        .header-brand {{
            display: flex;
            align-items: center;
            gap: 14px;
        }}
        .header-logo {{
            width: 52px;
            height: 52px;
            background: rgba(255,255,255,0.15);
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 26px;
            border: 1px solid rgba(255,255,255,0.25);
        }}
        .header-title {{ color: white; }}
        .header-title h1 {{ font-size: 20px; font-weight: 800; letter-spacing: -0.3px; }}
        .header-title p {{ font-size: 12px; color: rgba(255,255,255,0.75); margin-top: 2px; }}
        .header-right {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .live-clock {{
            background: rgba(255,255,255,0.12);
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 10px;
            padding: 8px 16px;
            color: white;
            font-size: 15px;
            font-weight: 600;
            font-variant-numeric: tabular-nums;
            min-width: 100px;
            text-align: center;
        }}
        .refresh-btn {{
            background: rgba(255,255,255,0.15);
            border: 1px solid rgba(255,255,255,0.3);
            color: white;
            padding: 8px 16px;
            border-radius: 10px;
            font-size: 13px;
            font-weight: 600;
            text-decoration: none;
            cursor: pointer;
            transition: background 0.2s;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .refresh-btn:hover {{ background: rgba(255,255,255,0.28); }}

        /* ── DATE NAV BAR ── */
        .date-bar {{
            background: white;
            border-bottom: 1px solid var(--border);
        }}
        .date-bar-inner {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 14px 28px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 12px;
        }}
        .date-info {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .date-text {{
            font-size: 17px;
            font-weight: 700;
            color: var(--primary-dark);
        }}
        .day-text {{
            font-size: 13px;
            color: var(--text-muted);
            font-weight: 500;
        }}
        .today-badge {{
            background: var(--primary);
            color: white;
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 700;
        }}
        .date-nav {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .date-nav a {{
            padding: 7px 14px;
            border: 1.5px solid var(--border);
            border-radius: 8px;
            text-decoration: none;
            color: var(--text-muted);
            font-size: 13px;
            font-weight: 600;
            transition: all 0.15s;
        }}
        .date-nav a:hover {{ background: var(--primary-light); border-color: var(--accent); color: var(--primary); }}
        .date-nav a.today-btn {{ background: var(--primary); color: white; border-color: var(--primary); }}
        .date-nav a.today-btn:hover {{ background: var(--primary-dark); }}

        /* ── CONTAINER & LAYOUT ── */
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 24px 28px;
        }}
        .dashboard-layout {{
            display: grid;
            grid-template-columns: 2.2fr 1fr;
            gap: 24px;
            align-items: start;
        }}
        @media (max-width: 950px) {{
            .dashboard-layout {{
                grid-template-columns: 1fr;
            }}
        }}

        /* ── STAT CARDS ── */
        .stats-row {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 16px;
            margin-bottom: 24px;
        }}
        .stat-card {{
            background: white;
            border-radius: var(--radius);
            padding: 20px 24px;
            box-shadow: var(--shadow);
            display: flex;
            align-items: center;
            gap: 16px;
        }}
        .stat-icon {{
            width: 48px;
            height: 48px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 22px;
            flex-shrink: 0;
        }}
        .stat-icon.blue {{ background: var(--primary-light); }}
        .stat-icon.green {{ background: var(--green-bg); }}
        .stat-icon.yellow {{ background: var(--yellow-bg); }}
        .stat-value {{ font-size: 28px; font-weight: 800; color: var(--text); line-height: 1; }}
        .stat-label {{ font-size: 12px; color: var(--text-muted); font-weight: 500; margin-top: 4px; }}

        /* ── DOCTOR CARD ── */
        .doctor-card {{
            background: var(--card-bg);
            border-radius: var(--radius);
            margin-bottom: 20px;
            box-shadow: var(--shadow);
            overflow: hidden;
            border: 1px solid var(--border);
        }}
        .doctor-header {{
            padding: 18px 24px;
            background: linear-gradient(135deg, #eff6ff 0%, #e0f2fe 100%);
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #bfdbfe;
        }}
        .doctor-left {{
            display: flex;
            align-items: center;
            gap: 14px;
        }}
        .doc-icon {{
            width: 44px;
            height: 44px;
            background: white;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 22px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }}
        .doc-name {{ font-size: 17px; font-weight: 700; color: var(--primary-dark); }}
        .doc-dept {{
            display: inline-block;
            margin-top: 4px;
            background: var(--primary);
            color: white;
            padding: 2px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 600;
        }}
        .doc-right {{ text-align: center; }}
        .doc-count {{ font-size: 28px; font-weight: 800; color: var(--primary); }}
        .doc-count-label {{ font-size: 11px; color: var(--text-muted); font-weight: 500; }}

        /* ── SIDEBAR DOCTOR TIMINGS ── */
        .sidebar-card {{
            background: white;
            border-radius: var(--radius);
            padding: 24px;
            box-shadow: var(--shadow);
            border: 1px solid var(--border);
            position: sticky;
            top: 24px;
        }}
        .sidebar-title {{
            font-size: 16px;
            font-weight: 800;
            color: var(--primary-dark);
            margin-bottom: 18px;
            display: flex;
            align-items: center;
            gap: 8px;
            border-bottom: 2px solid var(--primary-light);
            padding-bottom: 10px;
        }}
        .sidebar-doc-item {{
            padding: 16px 0;
            border-bottom: 1px dashed var(--border);
        }}
        .sidebar-doc-item:last-child {{
            border-bottom: none;
            padding-bottom: 0;
        }}
        .sidebar-doc-item:first-child {{
            padding-top: 0;
        }}
        .sidebar-doc-name {{
            font-size: 15px;
            font-weight: 700;
            color: var(--text);
        }}
        .sidebar-doc-dept {{
            font-size: 10px;
            font-weight: 700;
            background: var(--primary-light);
            color: var(--primary-dark);
            padding: 2px 8px;
            border-radius: 12px;
            display: inline-block;
            margin-top: 4px;
            text-transform: uppercase;
        }}
        .sidebar-doc-detail {{
            font-size: 12px;
            color: var(--text-muted);
            margin-top: 8px;
            display: flex;
            justify-content: space-between;
            font-weight: 500;
        }}
        .slots-badge {{
            background: var(--green-bg);
            color: var(--green);
            padding: 2px 8px;
            border-radius: 6px;
            font-weight: 700;
            font-size: 11px;
        }}
        .slots-badge.empty {{
            background: #fee2e2;
            color: #ef4444;
        }}

        /* ── TABLE ── */
        .table-wrap {{ overflow-x: auto; }}
        table {{ width: 100%; border-collapse: collapse; }}
        thead tr {{ background: #f8fafc; }}
        th {{
            padding: 11px 16px;
            text-align: left;
            font-size: 11px;
            font-weight: 700;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.06em;
            border-bottom: 1.5px solid var(--border);
            white-space: nowrap;
        }}
        td {{
            padding: 13px 16px;
            border-bottom: 1px solid #f1f5f9;
            font-size: 14px;
            vertical-align: middle;
        }}
        .appt-row:last-child td {{ border-bottom: none; }}
        .appt-row:hover {{ background: #f8fafc; }}
        .td-sno {{ color: #cbd5e1; font-weight: 700; font-size: 13px; width: 36px; }}
        .time-pill {{
            background: var(--primary-light);
            color: var(--primary-dark);
            padding: 5px 12px;
            border-radius: 20px;
            font-weight: 700;
            font-size: 13px;
            white-space: nowrap;
            display: inline-block;
        }}
        .patient-name {{ font-weight: 600; color: var(--text); font-size: 14px; }}
        .phone-link {{ color: var(--text-muted); text-decoration: none; font-size: 13px; white-space: nowrap; }}
        .phone-link:hover {{ color: var(--primary); }}
        .td-reason {{ color: var(--text-muted); font-size: 13px; max-width: 180px; }}
        .badge {{
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 700;
            white-space: nowrap;
            display: inline-block;
        }}
        .badge.confirmed {{ background: var(--green-bg); color: var(--green); }}
        .badge.pending-pay {{ background: var(--yellow-bg); color: var(--yellow); }}

        /* ── EMPTY STATE ── */
        .empty-card {{
            background: white;
            border-radius: var(--radius);
            padding: 60px 20px;
            text-align: center;
            box-shadow: var(--shadow);
            border: 1px solid var(--border);
        }}
        .empty-icon {{ font-size: 52px; margin-bottom: 16px; }}
        .empty-card h3 {{ font-size: 18px; font-weight: 700; color: var(--text); margin-bottom: 8px; }}
        .empty-card p {{ font-size: 14px; color: var(--text-muted); max-width: 360px; margin: 0 auto; }}

        /* ── FOOTER ── */
        .footer {{
            text-align: center;
            color: #94a3b8;
            font-size: 12px;
            padding: 20px;
        }}

        /* ── RESPONSIVE ── */
        @media (max-width: 700px) {{
            .header-inner, .date-bar-inner, .container {{ padding: 14px 16px; }}
            .stats-row {{ grid-template-columns: 1fr; }}
            th, td {{ padding: 10px 12px; }}
            .header-title h1 {{ font-size: 16px; }}
            .date-text {{ font-size: 14px; }}
        }}
        @media (max-width: 480px) {{
            .stats-row {{ grid-template-columns: 1fr 1fr; }}
            .stat-card:first-child {{ grid-column: span 2; }}
        }}
    </style>
    <meta http-equiv="refresh" content="30">
</head>
<body>

    <div class="header">
        <div class="header-inner">
            <div class="header-brand">
                <div class="header-logo">🏥</div>
                <div class="header-title">
                    <h1>{hosp_name}</h1>
                    <p>रिसेप्शनिस्ट डैशबोर्ड — AI Voice Booking System</p>
                </div>
            </div>
            <div class="header-right">
                <div class="live-clock" id="clock">{now_str}</div>
                <a class="refresh-btn" href="/receptionist/schedule?hospital_id={hospital_id}">
                    🔄 Refresh
                </a>
            </div>
        </div>
    </div>

    <div class="date-bar">
        <div class="date-bar-inner">
            <div class="date-info">
                <div>
                    <div class="date-text">📅 {day_display} {today_flag}</div>
                    <div class="day-text">{day_name}</div>
                </div>
            </div>
            <div class="date-nav">
                <a href="/receptionist/schedule?date_str={prev_date}&hospital_id={hospital_id}">◀ पिछला</a>
                <a href="/receptionist/schedule?hospital_id={hospital_id}" class="today-btn">आज</a>
                <a href="/receptionist/schedule?date_str={next_date}&hospital_id={hospital_id}">अगला ▶</a>
            </div>
        </div>
    </div>

    <div class="container">

        <div class="stats-row">
            <div class="stat-card">
                <div class="stat-icon blue">📋</div>
                <div>
                    <div class="stat-value">{total}</div>
                    <div class="stat-label">कुल अपॉइंटमेंट</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon green">✅</div>
                <div>
                    <div class="stat-value">{confirmed}</div>
                    <div class="stat-label">Confirmed</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon yellow">⏳</div>
                <div>
                    <div class="stat-value">{pending}</div>
                    <div class="stat-label">Payment Pending</div>
                </div>
            </div>
        </div>

        <div class="dashboard-layout">
            <!-- Left Side: Appointments List -->
            <div class="main-content">
                {doctor_sections}
            </div>

            <!-- Right Side: Doctors & Timings Sidebar -->
            <div class="sidebar-content">
                <div class="sidebar-card">
                    <div class="sidebar-title">
                        <span>👨‍⚕️</span> डॉक्टर, समय एवं फीस सूची
                    </div>
                    <div class="sidebar-list">
                        {sidebar_html}
                    </div>
                </div>
            </div>
        </div>

        <div class="footer">
            यह पेज हर <strong>30 सेकंड</strong> में auto refresh होता है &nbsp;·&nbsp;
            अंतिम अपडेट: {datetime.now().strftime("%d %b %Y, %I:%M:%S %p")}
        </div>
    </div>

    <script>
        // Live clock update every second
        function updateClock() {{
            const now = new Date();
            const h = String(now.getHours() % 12 || 12).padStart(2, '0');
            const m = String(now.getMinutes()).padStart(2, '0');
            const s = String(now.getSeconds()).padStart(2, '0');
            const ampm = now.getHours() >= 12 ? 'PM' : 'AM';
            document.getElementById('clock').textContent = h + ':' + m + ':' + s + ' ' + ampm;
        }}
        setInterval(updateClock, 1000);
        updateClock();
    </script>

</body>
</html>"""
    return HTMLResponse(content=html)


# ==========================================
# SIMULATED PAYMENT WEBHOOK & CHECKOUT GATEWAY
# ==========================================

@router.get("/payment/checkout", response_class=HTMLResponse, tags=["payment"])
async def payment_checkout_page(
    appt: str = Query(..., description="Full ID or last 8 characters of the appointment ID"),
    db: AsyncSession = Depends(get_db)
):
    """
    Simulated CP Tiwari Hospital payment checkout page.
    Renders details, billing amount, and simulated gateway confirm button.
    """
    from app.database.models.appointment import Appointment, Patient, Doctor, Department
    
    # Query appointment by full ID or last 8 characters
    if len(appt.strip()) == 8:
        stmt = (
            select(Appointment, Patient, Doctor, Department)
            .join(Patient, Appointment.patient_id == Patient.id)
            .join(Doctor, Appointment.doctor_id == Doctor.id)
            .join(Department, Doctor.department_id == Department.id)
            .where(Appointment.id.like(f"%{appt.strip()}"))
        )
    else:
        stmt = (
            select(Appointment, Patient, Doctor, Department)
            .join(Patient, Appointment.patient_id == Patient.id)
            .join(Doctor, Appointment.doctor_id == Doctor.id)
            .join(Department, Doctor.department_id == Department.id)
            .where(Appointment.id == appt.strip())
        )

    res = (await db.execute(stmt)).first()
    if not res:
        return HTMLResponse(
            content="<h3>त्रुटि (Error): अपॉइंटमेंट नहीं मिला। कृपया लिंक दोबारा जांचें।</h3>",
            status_code=404
        )

    appointment, patient, doctor, department = res
    appt_display_time = appointment.appointment_datetime.strftime("%d %b %Y, %I:%M %p")
    fees_map = {"doc_ortho": 500, "doc_cardio": 800, "doc_eye": 400}
    amount = fees_map.get(doctor.id, 500)

    # Check if already paid
    if appointment.status == "SCHEDULED":
        return HTMLResponse(content=f"""<!DOCTYPE html>
<html lang="hi">
<head>
    <meta charset="UTF-8">
    <title>पेमेंट रसीद — CP Tiwari Hospital</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        body {{ font-family: 'Inter', sans-serif; background: #f0f5fc; color: #0f172a; padding: 40px 20px; text-align: center; }}
        .card {{ background: white; max-width: 480px; margin: 0 auto; padding: 40px; border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); border: 1px solid #e2e8f0; }}
        .success-icon {{ font-size: 56px; color: #16a34a; margin-bottom: 20px; }}
        h2 {{ font-size: 22px; font-weight: 800; color: #0f3276; margin-bottom: 12px; }}
        p {{ color: #64748b; font-size: 14px; margin-bottom: 24px; line-height: 1.5; }}
        .details {{ text-align: left; background: #f8fafc; padding: 20px; border-radius: 12px; margin-bottom: 24px; border: 1px dashed #cbd5e1; }}
        .detail-row {{ display: flex; justify-content: space-between; margin-bottom: 10px; font-size: 13px; }}
        .detail-row:last-child {{ margin-bottom: 0; }}
        .label {{ color: #64748b; font-weight: 500; }}
        .val {{ color: #0f172a; font-weight: 700; }}
        .badge {{ background: #dcfce7; color: #16a34a; padding: 4px 10px; border-radius: 8px; font-weight: 700; }}
        .btn {{ display: inline-block; background: #0f3276; color: white; padding: 12px 24px; border-radius: 10px; text-decoration: none; font-weight: 600; font-size: 14px; margin-top: 10px; }}
        .btn:hover {{ background: #1a4fa0; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="success-icon">🎉</div>
        <h2>पेमेंट पहले ही हो चुका है!</h2>
        <p>इस अपॉइंटमेंट के लिए पेमेंट सफलतापूर्वक प्राप्त हो चुका है और अपॉइंटमेंट कन्फर्म है।</p>
        <div class="details">
            <div class="detail-row"><span class="label">मरीज़:</span><span class="val">{patient.first_name} {patient.last_name}</span></div>
            <div class="detail-row"><span class="label">डॉक्टर:</span><span class="val">Dr. {doctor.first_name} {doctor.last_name}</span></div>
            <div class="detail-row"><span class="label">समय:</span><span class="val">{appt_display_time}</span></div>
            <div class="detail-row"><span class="label">राशि:</span><span class="val">₹{amount} (Paid)</span></div>
            <div class="detail-row"><span class="label">स्थिति:</span><span class="val"><span class="badge">कन्फर्म (Confirmed)</span></span></div>
        </div>
        <a href="/receptionist/schedule" class="btn">डैशबोर्ड पर जाएं</a>
    </div>
</body>
</html>""")

    checkout_html = f"""<!DOCTYPE html>
<html lang="hi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>सुरक्षित भुगतान द्वार (Checkout) — CP Tiwari Hospital</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {{
            --primary: #1a4fa0;
            --primary-dark: #0f3276;
            --primary-light: #dbeafe;
            --bg: #f0f5fc;
            --text: #0f172a;
            --text-muted: #64748b;
            --border: #e2e8f0;
            --radius: 16px;
        }}
        body {{
            font-family: 'Inter', sans-serif;
            background: var(--bg);
            color: var(--text);
            padding: 40px 20px;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .checkout-box {{
            background: white;
            width: 100%;
            max-width: 480px;
            border-radius: var(--radius);
            box-shadow: 0 10px 30px rgba(15,50,118,0.12);
            border: 1px solid var(--border);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #0f3276 0%, #1a4fa0 100%);
            padding: 24px;
            color: white;
            text-align: center;
        }}
        .header h2 {{ font-size: 20px; font-weight: 800; letter-spacing: -0.3px; }}
        .header p {{ font-size: 12px; color: rgba(255,255,255,0.8); margin-top: 4px; }}
        .body {{
            padding: 28px;
        }}
        .summary-card {{
            background: #f8fafc;
            border-radius: 12px;
            padding: 20px;
            border: 1px solid var(--border);
            margin-bottom: 24px;
        }}
        .summary-title {{
            font-size: 13px;
            font-weight: 700;
            color: var(--primary-dark);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 14px;
            border-bottom: 1.5px solid var(--primary-light);
            padding-bottom: 6px;
        }}
        .summary-row {{
            display: flex;
            justify-content: space-between;
            margin-bottom: 10px;
            font-size: 13.5px;
        }}
        .summary-row:last-child {{ margin-bottom: 0; }}
        .label {{ color: var(--text-muted); font-weight: 500; }}
        .value {{ color: var(--text); font-weight: 700; }}
        
        .amount-card {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: #eff6ff;
            border: 1px solid #bfdbfe;
            padding: 16px 20px;
            border-radius: 12px;
            margin-bottom: 24px;
        }}
        .amount-label {{ font-size: 14px; font-weight: 600; color: var(--primary-dark); }}
        .amount-val {{ font-size: 24px; font-weight: 800; color: var(--primary-dark); }}

        .pay-btn {{
            width: 100%;
            background: #16a34a;
            color: white;
            border: none;
            padding: 14px 20px;
            border-radius: 10px;
            font-size: 15px;
            font-weight: 700;
            cursor: pointer;
            transition: background 0.2s;
            box-shadow: 0 4px 12px rgba(22,163,74,0.25);
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }}
        .pay-btn:hover {{ background: #15803d; }}
        .pay-btn:disabled {{ background: #a3a3a3; cursor: not-allowed; box-shadow: none; }}
        
        .footer {{
            text-align: center;
            font-size: 11px;
            color: var(--text-muted);
            margin-top: 20px;
        }}
    </style>
</head>
<body>

    <div class="checkout-box">
        <div class="header">
            <h2>🏥 CP Tiwari Hospital</h2>
            <p>सुरक्षित ओपीडी भुगतान पोर्टल (Secure Payment Gateway)</p>
        </div>
        <div class="body">
            <div class="summary-card">
                <div class="summary-title">अपॉइंटमेंट सारांश</div>
                <div class="summary-row">
                    <span class="label">मरीज़ का नाम:</span>
                    <span class="value">{patient.first_name} {patient.last_name}</span>
                </div>
                <div class="summary-row">
                    <span class="label">मोबाइल नंबर:</span>
                    <span class="value">{patient.phone}</span>
                </div>
                <div class="summary-row">
                    <span class="label">डॉक्टर का नाम:</span>
                    <span class="value">Dr. {doctor.first_name} {doctor.last_name} ({department.name})</span>
                </div>
                <div class="summary-row">
                    <span class="label">दिनांक व समय:</span>
                    <span class="value">{appt_display_time}</span>
                </div>
                <div class="summary-row">
                    <span class="label">भुगतान स्थिति:</span>
                    <span class="value" style="color: var(--yellow);">⏳ Payment Pending</span>
                </div>
            </div>

            <div class="amount-card">
                <span class="amount-label">कुल भुगतान राशि:</span>
                <span class="amount-val">₹{amount}</span>
            </div>

            <button class="pay-btn" id="payBtn" onclick="processPayment()">
                🔒 भुगतान करें (Pay ₹{amount})
            </button>
            
            <div class="footer">
                🛡️ PCI-DSS अनुपालन • 256-Bit SSL सुरक्षित एन्क्रिप्शन
            </div>
        </div>
    </div>

    <script>
        async function processPayment() {{
            const btn = document.getElementById('payBtn');
            btn.disabled = true;
            btn.textContent = '🔄 भुगतान संसाधित किया जा रहा है...';

            try {{
                const response = await fetch('/payment/confirm/{appointment.id}', {{
                    method: 'POST'
                }});
                const result = await response.json();
                
                if (result.success) {{
                    // Show custom success state
                    document.body.innerHTML = `
                        <div class="checkout-box" style="text-align: center; padding: 40px; max-width: 440px;">
                            <div style="font-size: 56px; color: #16a34a; margin-bottom: 20px;">🎉</div>
                            <h2 style="font-size: 22px; font-weight: 800; color: #0f3276; margin-bottom: 12px;">भुगतान सफल रहा!</h2>
                            <p style="color: #64748b; font-size: 14px; margin-bottom: 24px; line-height: 1.5;">
                                आपका भुगतान सफलतापूर्वक प्राप्त हो गया है। आपकी अपॉइंटमेंट अब <b>Confirmed (कन्फर्म)</b> है।<br><br>
                                अंतिम अपॉइंटमेंट रसीद आपके पंजीकृत मोबाइल <b>${{result.phone}}</b> पर WhatsApp कर दी गई है।
                            </p>
                            <a href="/receptionist/schedule" style="display: inline-block; background: #0f3276; color: white; padding: 12px 24px; border-radius: 10px; text-decoration: none; font-weight: 600; font-size: 14px;">डैशबोर्ड पर जाएं</a>
                        </div>
                    `;
                }} else {{
                    alert('त्रुटि: भुगतान असफल रहा। कृपया पुनः प्रयास करें।');
                    btn.disabled = false;
                    btn.textContent = '🔒 भुगतान करें (Pay ₹{amount})';
                }}
            }} catch (err) {{
                alert('तकनीकी त्रुटि। नेटवर्क की जांच करें।');
                btn.disabled = false;
                btn.textContent = '🔒 भुगतान करें (Pay ₹{amount})';
            }}
        }}
    </script>

</body>
</html>"""
    return HTMLResponse(content=checkout_html)


@router.post("/payment/confirm/{appointment_id}", tags=["payment"])
async def payment_confirmation_webhook(
    appointment_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Web-hook simulation triggered upon payment success.
    Updates appointment status to SCHEDULED (Confirmed) and dispatches patient WhatsApp notification.
    """
    from app.database.models.appointment import Appointment, Patient, Doctor, AppointmentStatusHistory
    from app.services.whatsapp import WhatsAppNotificationService

    stmt = (
        select(Appointment)
        .where(Appointment.id == appointment_id)
    )
    appointment = (await db.execute(stmt)).scalar_one_or_none()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found.")

    if appointment.status == "SCHEDULED":
        return {"success": True, "message": "Already confirmed", "phone": "N/A"}

    # Update status to SCHEDULED (Confirmed)
    old_status = appointment.status
    appointment.status = "SCHEDULED"
    appointment.updated_at = datetime.now()

    # Log status change in history
    status_history = AppointmentStatusHistory(
        id=str(uuid.uuid4()),
        appointment_id=appointment.id,
        previous_status=old_status,
        new_status="SCHEDULED",
        change_reason="Payment confirmed successfully via online portal"
    )
    db.add(status_history)
    
    # Flush database so changes are visible
    await db.flush()

    # Load Patient, Doctor details for sending WhatsApp
    patient_stmt = select(Patient).where(Patient.id == appointment.patient_id)
    patient = (await db.execute(patient_stmt)).scalar_one_or_none()
    
    doctor_stmt = select(Doctor).where(Doctor.id == appointment.doctor_id)
    doctor = (await db.execute(doctor_stmt)).scalar_one_or_none()

    await db.commit()

    if patient and doctor:
        wa_service = WhatsAppNotificationService()
        wa_details = {
            "appointment_id": appointment.id,
            "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
            "patient_phone": patient.phone,
            "doctor_name": f"Dr. {doctor.first_name} {doctor.last_name}",
            "appointment_datetime": appointment.appointment_datetime.isoformat(),
            "reason": appointment.reason
        }
        # Trigger WhatsApp notification task in background
        asyncio.create_task(wa_service.send_payment_confirmation(wa_details))

    return {
        "success": True,
        "message": "Payment confirmed successfully and WhatsApp dispatched.",
        "phone": patient.phone if patient else ""
    }


