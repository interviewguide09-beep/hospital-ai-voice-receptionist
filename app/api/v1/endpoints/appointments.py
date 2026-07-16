import uuid
import asyncio
from datetime import date, datetime, timezone, timedelta
from typing import List, Optional
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, status, Query, Form
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import HTMLResponse
from sqlalchemy import select, and_, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.session import get_db
from app.core.dependencies import create_access_token, verify_password, get_current_user, hash_password
from app.core.config import settings
from app.core.logging import logger
from app.database.models.call_log import User, Role, UserRole


async def auto_update_missed_appointments(db: AsyncSession):
    """
    Sweeper that auto-marks expired appointments as MISSED:
    1. Unpaid (PENDING_PAYMENT) is marked MISSED immediately after appointment_datetime has passed.
    2. Paid (SCHEDULED) is marked MISSED after appointment_datetime has passed AND 2 days (48h) have elapsed since original booking (created_at).
    """
    try:
        now = datetime.now()
        
        # 1. Unpaid expired -> MISSED instantly
        stmt_unpaid = (
            update(Appointment)
            .where(
                and_(
                    Appointment.status == "PENDING_PAYMENT",
                    Appointment.appointment_datetime < now
                )
            )
            .values(status="MISSED", updated_at=now)
        )
        await db.execute(stmt_unpaid)

        # 2. Paid expired -> MISSED if not rescheduled within 2 days of booking (created_at)
        two_days_ago = now - timedelta(days=2)
        stmt_paid = (
            update(Appointment)
            .where(
                and_(
                    Appointment.status == "SCHEDULED",
                    Appointment.appointment_datetime < now,
                    Appointment.created_at < two_days_ago
                )
            )
            .values(status="MISSED", updated_at=now)
        )
        await db.execute(stmt_paid)
        await db.commit()
    except Exception as e:
        logger.error(f"Error running auto-missed sweep: {str(e)}", exc_info=True)

from app.database.models.appointment import Doctor, Patient, Hospital, Department, Appointment
from app.engines.appointment import AppointmentEngine
from app.engines.scheduling import SchedulingEngine
from app.schemas.appointment import (
    AppointmentCreate, AppointmentRead, AppointmentUpdate,
    DoctorCreate, DoctorRead, PatientCreate, PatientRead,
    AvailableSlotsResponse, SlotQuery
)


class PaymentOrderRequest(BaseModel):
    appointment_id: str
    amount: int

class PaymentVerifyRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    appointment_id: str

router = APIRouter()


# ==========================================
# HOSPITALS LIST (Super Admin)
# ==========================================

@router.get("/hospitals", tags=["admin"])
async def list_hospitals(db: AsyncSession = Depends(get_db)):
    """Super Admin: Returns all registered hospitals with their details."""
    from app.database.models.appointment import HospitalSetting
    stmt = select(Hospital)
    hospitals = (await db.execute(stmt)).scalars().all()
    result = []
    for h in hospitals:
        # Fetch Twilio settings
        sid_stmt = select(HospitalSetting).where(HospitalSetting.hospital_id == h.id, HospitalSetting.setting_key == "twilio_account_sid")
        sid_row = (await db.execute(sid_stmt)).scalar_one_or_none()
        sid_val = sid_row.setting_value if sid_row else (settings.TWILIO_ACCOUNT_SID if h.id == "hosp_default" else "")

        token_stmt = select(HospitalSetting).where(HospitalSetting.hospital_id == h.id, HospitalSetting.setting_key == "twilio_auth_token")
        token_row = (await db.execute(token_stmt)).scalar_one_or_none()
        token_val = token_row.setting_value if token_row else (settings.TWILIO_AUTH_TOKEN if h.id == "hosp_default" else "")

        helpline_stmt = select(HospitalSetting).where(HospitalSetting.hospital_id == h.id, HospitalSetting.setting_key == "twilio_helpline")
        helpline_row = (await db.execute(helpline_stmt)).scalar_one_or_none()
        helpline_val = helpline_row.setting_value if helpline_row else (settings.TWILIO_PHONE_NUMBER if h.id == "hosp_default" else h.phone)

        result.append({
            "id": h.id,
            "name": h.name,
            "slug": h.slug,
            "phone": h.phone,
            "email": h.email,
            "address": h.address,
            "is_active": h.is_active,
            "created_at": str(h.created_at),
            "helpline": helpline_val,
            "twilio_account_sid": sid_val,
            "twilio_auth_token": token_val
        })
    return result


@router.delete("/hospitals/{hospital_id}", tags=["admin"])
async def delete_hospital(
    hospital_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Super Admin: Deletes a registered hospital and all associated records."""
    role_stmt = select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == current_user.id)
    roles = (await db.execute(role_stmt)).scalars().all()
    if "SUPER_ADMIN" not in roles and current_user.username != "shiva9532":
        raise HTTPException(status_code=403, detail="Unauthorized: Only Platform Owner can delete hospitals.")

    # 1. Fetch Hospital
    hosp_stmt = select(Hospital).where(Hospital.id == hospital_id)
    hospital = (await db.execute(hosp_stmt)).scalar_one_or_none()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    # 2. Prevent deleting default tenant
    if hospital_id == "hosp_default":
        raise HTTPException(status_code=400, detail="Cannot delete default hospital tenant.")

    # 3. Delete hospital
    await db.delete(hospital)
    
    # 4. Clean up users
    users_stmt = select(User).where(User.hospital_id == hospital_id)
    users = (await db.execute(users_stmt)).scalars().all()
    for u in users:
        await db.delete(u)

    await db.commit()
    return {"success": True, "message": "Hospital and associated records deleted successfully."}


@router.post("/hospitals/{hospital_id}/twilio", tags=["admin"])
async def save_hospital_twilio(
    hospital_id: str,
    account_sid: str = Form(...),
    auth_token: str = Form(...),
    helpline: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Super Admin: Saves custom Twilio configuration parameters for a specific hospital tenant."""
    role_stmt = select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == current_user.id)
    roles = (await db.execute(role_stmt)).scalars().all()
    if "SUPER_ADMIN" not in roles and current_user.username != "shiva9532":
        raise HTTPException(status_code=403, detail="Unauthorized: Only Platform Owner can configure Twilio.")

    from app.database.models.appointment import HospitalSetting
    import uuid

    async def set_setting(key: str, val: str):
        stmt = select(HospitalSetting).where(HospitalSetting.hospital_id == hospital_id, HospitalSetting.setting_key == key)
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row:
            row.setting_value = val
        else:
            new_row = HospitalSetting(
                id=str(uuid.uuid4()),
                hospital_id=hospital_id,
                setting_key=key,
                setting_value=val
            )
            db.add(new_row)

    await set_setting("twilio_account_sid", account_sid)
    await set_setting("twilio_auth_token", auth_token)
    await set_setting("twilio_helpline", helpline)
    
    await db.commit()
    return {"success": True, "message": "Twilio configuration persisted successfully."}


# ==========================================
# HOSPITAL DEPARTMENTS (Dropdown lookup)
# ==========================================

@router.get("/hospital/departments", tags=["hospital"])
async def get_hospital_departments(db: AsyncSession = Depends(get_db)):
    """Returns list of all active departments for onboarding."""
    stmt = select(Department).where(Department.is_active == True)
    depts = (await db.execute(stmt)).scalars().all()
    return [{"id": d.id, "name": d.name} for d in depts]


# ==========================================
# HOSPITAL ANALYTICS & STATS (Admin Metrics)
# ==========================================

@router.get("/hospital/stats", tags=["hospital"])
async def get_hospital_stats(current_admin: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Fetch analytics, revenue, doctor bookings, and doctors list for the Hospital Admin."""
    role_stmt = select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == current_admin.id)
    roles = (await db.execute(role_stmt)).scalars().all()
    if "ADMIN" not in roles and "SUPER_ADMIN" not in roles:
        raise HTTPException(status_code=403, detail="Unauthorized")

    hosp_id = current_admin.hospital_id if current_admin.hospital_id else "hosp_default"
    h_stmt = select(Hospital).where(Hospital.id == hosp_id)
    hosp = (await db.execute(h_stmt)).scalar_one_or_none()
    hospital_phone = hosp.phone if hosp else ""

    # Get all doctors
    doctors_stmt = select(Doctor, Department).join(Department, Doctor.department_id == Department.id).where(Doctor.hospital_id == hosp_id)
    doctors_db = (await db.execute(doctors_stmt)).all()

    # Get all appointments for this hospital
    appts_stmt = select(Appointment, Doctor).join(Doctor, Appointment.doctor_id == Doctor.id).where(Doctor.hospital_id == hosp_id)
    appts_db = (await db.execute(appts_stmt)).all()

    # Calculate statistics
    paid_bookings = [a for a, d in appts_db if a.payment_status == "PAID"]
    fees_map = {"doc_ortho": 500, "doc_cardio": 800, "doc_eye": 400}
    total_revenue = sum([d.opd_fees if d.opd_fees else fees_map.get(d.id, 500) for a, d in paid_bookings])

    # Doctor booking counts
    doc_bookings = {}
    for doc, dept in doctors_db:
        doc_bookings[doc.id] = {
            "id": doc.id,
            "name": f"Dr. {doc.first_name} {doc.last_name}",
            "department": dept.name,
            "license": doc.license_number or "N/A",
            "is_active": doc.is_active,
            "opd_fees": doc.opd_fees or fees_map.get(doc.id, 500),
            "booking_count": 0,
            "revenue": 0
        }

    for appt, doc in appts_db:
        if doc.id in doc_bookings:
            doc_bookings[doc.id]["booking_count"] += 1
            if appt.payment_status == "PAID":
                doc_bookings[doc.id]["revenue"] += doc.opd_fees if doc.opd_fees else fees_map.get(doc.id, 500)

    return {
        "hospital_id": hosp_id,
        "hospital_phone": hospital_phone,
        "total_revenue": total_revenue,
        "total_bookings": len(appts_db),
        "active_doctors_count": len(doctors_db),
        "doctors": list(doc_bookings.values())
    }


# ==========================================
# AUTHENTICATION & MULTI-SAAS ONBOARDING  
# ==========================================

@router.post("/auth/register-hospital", tags=["auth"])
async def register_hospital(
    name: str = Form(..., description="Hospital Name"),
    address: Optional[str] = Form(None, description="Hospital Address"),
    phone: str = Form(..., description="Hospital phone (for notifications/helpline)"),
    admin_username: str = Form(..., description="Admin Username"),
    admin_email: str = Form(..., description="Admin Email (Gmail)"),
    admin_password: str = Form(..., description="Admin Password"),
    db: AsyncSession = Depends(get_db)
):
    """
    Onboards a new Hospital tenant, creates a unique Hospital ID,
    and registers the Hospital Admin user.
    """
    import random

    try:
        # 1. Check if user already exists
        stmt = select(User).where((User.username == admin_username) | (User.email == admin_email))
        existing_user = (await db.execute(stmt)).scalar_one_or_none()
        if existing_user:
            raise HTTPException(status_code=400, detail="Username or email already registered.")

        # 2. Generate unique Hospital ID
        prefix = "".join([c for c in name if c.isalnum()]).upper()[:4]
        if not prefix:
            prefix = "HOSP"
        
        unique_hosp_id = None
        for _ in range(10):  # try 10 times to avoid collision
            temp_id = f"HOSP-{prefix}-{random.randint(1000, 9999)}"
            chk_stmt = select(Hospital).where(Hospital.id == temp_id)
            exists = (await db.execute(chk_stmt)).scalar_one_or_none()
            if not exists:
                unique_hosp_id = temp_id
                break
                
        if not unique_hosp_id:
            unique_hosp_id = f"HOSP-{random.randint(100000, 999999)}"

        # Generate hospital slug
        slug = name.lower().replace(" ", "-")
        slug = "".join([c for c in slug if c.isalnum() or c == "-"])

        # 3. Create Hospital
        hospital = Hospital(
            id=unique_hosp_id,
            name=name,
            slug=slug,
            address=address,
            phone=phone,
            email=admin_email,
            is_active=True
        )
        db.add(hospital)
        await db.flush()

        # 4. Fetch or Create Role ADMIN
        role_stmt = select(Role).where(Role.name == "ADMIN")
        admin_role = (await db.execute(role_stmt)).scalar_one_or_none()
        if not admin_role:
            admin_role = Role(id=str(uuid.uuid4()), name="ADMIN", description="Hospital Administrator")
            db.add(admin_role)
            await db.flush()

        # 5. Create Admin User
        admin_user = User(
            id=str(uuid.uuid4()),
            hospital_id=unique_hosp_id,
            username=admin_username,
            email=admin_email,
            password_hash=hash_password(admin_password),
            is_active=True
        )
        db.add(admin_user)
        await db.flush()

        # 6. Map User to Role
        user_role = UserRole(
            id=str(uuid.uuid4()),
            user_id=admin_user.id,
            role_id=admin_role.id
        )
        db.add(user_role)
        await db.commit()

        # Send WhatsApp welcome message to hospital phone with all credentials
        try:
            from app.services.whatsapp import WhatsAppNotificationService
            import asyncio as _asyncio
            _wa = WhatsAppNotificationService()
            _msg = (
                f"🏥 *AURA SaaS — Hospital Registered Successfully!*\\n\\n"
                f"*Hospital Name:* {name}\\n"
                f"*Hospital ID:* {unique_hosp_id}\\n"
                f"*Address:* {address or 'N/A'}\\n\\n"
                f"🔑 *Admin Login Credentials:*\\n"
                f"• Username: {admin_username}\\n"
                f"• Password: {admin_password}\\n"
                f"• Email: {admin_email}\\n\\n"
                f"📌 Share the Hospital ID with your staff so they can login to their portals.\\n"
                f"_— AURA SaaS AI Platform_"
            )
            _asyncio.create_task(_wa.send_custom_notification(phone, _msg))
        except Exception:
            pass

        return {
            "success": True,
            "message": "Hospital registered successfully.",
            "hospital_id": unique_hosp_id,
            "hospital_slug": slug,
            "admin_username": admin_username
        }
    except Exception as e:
        print(f"Exception in register_hospital: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/hospital/register-staff", tags=["hospital"])
async def register_staff(
    role: str = Form(..., description="DOCTOR or RECEPTIONIST"),
    username: str = Form(..., description="Staff Username"),
    email: str = Form(..., description="Staff Email"),
    password: str = Form(..., description="Staff Password"),
    first_name: str = Form(..., description="Staff First Name"),
    last_name: str = Form(..., description="Staff Last Name"),
    phone: str = Form(..., description="Staff Phone Number"),
    # Doctor specific parameters (if registering a doctor)
    department_id: Optional[str] = Form(None, description="Department ID (required for DOCTOR)"),
    license_number: Optional[str] = Form(None, description="License Number (optional for DOCTOR)"),
    # Schedule fields
    schedule_days: Optional[str] = Form(None, description="Mon-Sun comma-separated values, e.g. 1,2,3,4,5"),
    schedule_start_time: Optional[str] = Form(None, description="Start time (HH:MM)"),
    schedule_end_time: Optional[str] = Form(None, description="End time (HH:MM)"),
    schedule_start_time_2: Optional[str] = Form(None, description="Session 2 start time"),
    schedule_end_time_2: Optional[str] = Form(None, description="Session 2 end time"),
    opd_fees: Optional[int] = Form(500, description="OPD Fees"),
    slot_duration_minutes: Optional[int] = Form(30, description="Slot Duration in Minutes"),
    current_admin: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Hospital Admin endpoint to add Doctors or Receptionists.
    Automatically links staff members to the admin's hospital_id, and dispatches credentials via WhatsApp.
    """
    from app.services.whatsapp import WhatsAppNotificationService

    # 1. Fetch admin roles to verify authorization
    role_stmt = select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == current_admin.id)
    roles = (await db.execute(role_stmt)).scalars().all()
    if "ADMIN" not in roles:
        raise HTTPException(status_code=403, detail="Only Hospital Admins can register staff.")

    # 2. Check if username or email already exists
    stmt = select(User).where((User.username == username) | (User.email == email))
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already registered.")

    # 3. Fetch or Create target Role (DOCTOR or RECEPTIONIST)
    role_name = role.upper()
    if role_name not in ["DOCTOR", "RECEPTIONIST"]:
        raise HTTPException(status_code=400, detail="Invalid role. Select DOCTOR or RECEPTIONIST.")

    target_role_stmt = select(Role).where(Role.name == role_name)
    target_role = (await db.execute(target_role_stmt)).scalar_one_or_none()
    if not target_role:
        target_role = Role(id=str(uuid.uuid4()), name=role_name, description=f"Hospital {role_name.capitalize()}")
        db.add(target_role)
        await db.flush()

    # 4. Create User Record
    staff_user = User(
        id=str(uuid.uuid4()),
        hospital_id=current_admin.hospital_id,
        username=username,
        email=email,
        password_hash=hash_password(password),
        is_active=True
    )
    db.add(staff_user)
    await db.flush()

    # 5. Map User to Role
    user_role = UserRole(
        id=str(uuid.uuid4()),
        user_id=staff_user.id,
        role_id=target_role.id
    )
    db.add(user_role)
    await db.flush()

    # 6. If role is DOCTOR, create Doctor record
    if role_name == "DOCTOR":
        if not department_id:
            raise HTTPException(status_code=400, detail="department_id is required when role is DOCTOR.")
        
        # Verify department_id belongs to the same hospital
        dept_stmt = select(Department).where(
            and_(
                Department.id == department_id,
                Department.hospital_id == current_admin.hospital_id
            )
        )
        dept = (await db.execute(dept_stmt)).scalar_one_or_none()
        if not dept:
            raise HTTPException(status_code=404, detail="Department not found in this hospital.")

        doctor = Doctor(
            id=staff_user.id,  # Use same ID for unified joins
            hospital_id=current_admin.hospital_id,
            department_id=department_id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            license_number=license_number,
            opd_fees=opd_fees,
            hashed_password=hash_password(password),
            is_active=True
        )
        db.add(doctor)
        await db.flush()

        # Save schedule details if provided
        if schedule_days and schedule_start_time and schedule_end_time:
            from datetime import time
            from app.database.models.appointment import DoctorSchedule
            try:
                start_h, start_m = map(int, schedule_start_time.split(':'))
                end_h, end_m = map(int, schedule_end_time.split(':'))
                t_start = time(start_h, start_m)
                t_end = time(end_h, end_m)

                t_start_2, t_end_2 = None, None
                if schedule_start_time_2 and schedule_end_time_2:
                    sh_2, sm_2 = map(int, schedule_start_time_2.split(':'))
                    eh_2, em_2 = map(int, schedule_end_time_2.split(':'))
                    t_start_2 = time(sh_2, sm_2)
                    t_end_2 = time(eh_2, em_2)

                days = [int(d.strip()) for d in schedule_days.split(',') if d.strip().isdigit()]
                for day in days:
                    s1 = DoctorSchedule(
                        id=str(uuid.uuid4()),
                        doctor_id=doctor.id,
                        day_of_week=day,
                        start_time=t_start,
                        end_time=t_end,
                        slot_duration_minutes=30
                    )
                    db.add(s1)
                    if t_start_2 and t_end_2:
                        s2 = DoctorSchedule(
                            id=str(uuid.uuid4()),
                            doctor_id=doctor.id,
                            day_of_week=day,
                            start_time=t_start_2,
                            end_time=t_end_2,
                            slot_duration_minutes=30
                        )
                        db.add(s2)
            except Exception as se:
                logger.error(f"Error saving doctor schedule: {str(se)}")

    # 7. Fetch hospital details for onboarding message
    hosp_stmt = select(Hospital).where(Hospital.id == current_admin.hospital_id)
    hospital = (await db.execute(hosp_stmt)).scalar_one_or_none()
    hospital_name = hospital.name if hospital else "CP Tiwari Hospital"

    await db.commit()

    # 8. Send WhatsApp notification with credentials
    wa_service = WhatsAppNotificationService()
    wa_details = {
        "phone": phone,
        "staff_name": f"{first_name} {last_name}".strip(),
        "hospital_name": hospital_name,
        "hospital_id": current_admin.hospital_id if current_admin.hospital_id else "hosp_default",
        "role": role_name,
        "username": username,
        "password": password,
        "login_url": f"{settings.PAYMENT_BASE_URL.split('/appointment')[0]}/login"
    }
    asyncio.create_task(wa_service.send_staff_credentials_notification(wa_details))

    return {
        "success": True,
        "message": f"{role_name.capitalize()} staff created successfully.",
        "username": username,
        "hospital_id": current_admin.hospital_id
    }


@router.post("/auth/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    """Authenticates admin console, receptionist, and doctor users, and yields secure JWT tokens with role scope."""
    # 1. Platform Owner Login (Super Admin)
    if form_data.username == "shiva9532" and form_data.password == "#@112233":
        access_token = create_access_token(data={
            "sub": "shiva9532",
            "role": "SUPER_ADMIN",
            "hospital_id": "super_admin",
            "hospital_slug": ""
        })
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "role": "SUPER_ADMIN",
            "hospital_id": "super_admin",
            "hospital_slug": "",
            "username": "shiva9532"
        }

    # 2. Existing Hospital Admin Login (CP Tiwari Hospital)
    if form_data.username == "admin_cp" and form_data.password == "password123":
        access_token = create_access_token(data={
            "sub": "admin_cp",
            "role": "ADMIN",
            "hospital_id": "hosp_default",
            "hospital_slug": "cp-tiwari-hospital"
        })
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "role": "ADMIN",
            "hospital_id": "hosp_default",
            "hospital_slug": "cp-tiwari-hospital",
            "username": "admin_cp"
        }

    # 3. Existing Hospital Doctor Login (CP Tiwari Hospital)
    if form_data.username == "doctor_cp" and form_data.password == "password123":
        access_token = create_access_token(data={
            "sub": "doctor_cp",
            "role": "DOCTOR",
            "hospital_id": "hosp_default",
            "hospital_slug": "cp-tiwari-hospital"
        })
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "role": "DOCTOR",
            "hospital_id": "hosp_default",
            "hospital_slug": "cp-tiwari-hospital",
            "username": "doctor_cp"
        }

    # 4. Existing Hospital Receptionist Login (CP Tiwari Hospital)
    if form_data.username == "receptionist_cp" and form_data.password == "password123":
        access_token = create_access_token(data={
            "sub": "receptionist_cp",
            "role": "RECEPTIONIST",
            "hospital_id": "hosp_default",
            "hospital_slug": "cp-tiwari-hospital"
        })
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "role": "RECEPTIONIST",
            "hospital_id": "hosp_default",
            "hospital_slug": "cp-tiwari-hospital",
            "username": "receptionist_cp"
        }

    stmt = select(User).where(User.username == form_data.username, User.is_active == True)
    user = (await db.execute(stmt)).scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.password_hash):
        # Admin bootstrapping logic (only if no users exist in database)
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
            access_token = create_access_token(data={"sub": "admin", "role": "ADMIN", "hospital_id": "hosp_default"})
            return {"access_token": access_token, "token_type": "bearer", "role": "ADMIN", "hospital_id": "hosp_default"}

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Load roles of the user
    role_stmt = select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user.id)
    roles = (await db.execute(role_stmt)).scalars().all()
    user_role = roles[0] if roles else "RECEPTIONIST"  # fallback

    # Load hospital details (if linked)
    hospital_slug = ""
    if user.hospital_id:
        hosp_stmt = select(Hospital).where(Hospital.id == user.hospital_id)
        hosp = (await db.execute(hosp_stmt)).scalar_one_or_none()
        if hosp:
            hospital_slug = hosp.slug

    access_token = create_access_token(data={
        "sub": user.username,
        "role": user_role,
        "hospital_id": user.hospital_id,
        "hospital_slug": hospital_slug
    })
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user_role,
        "hospital_id": user.hospital_id,
        "hospital_slug": hospital_slug,
        "username": user.username
    }


# ==========================================
# APPOINTMENT MANAGEMENT
# ==========================================

@router.get("/appointments", tags=["appointments"])
async def list_all_appointments(
    doctor_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieves all active appointments, optionally filtered by doctor."""
    stmt = (
        select(Appointment, Patient, Doctor, Department)
        .join(Patient, Appointment.patient_id == Patient.id)
        .join(Doctor, Appointment.doctor_id == Doctor.id)
        .join(Department, Doctor.department_id == Department.id)
    )
    if doctor_id:
        stmt = stmt.where(Appointment.doctor_id == doctor_id)
    else:
        if current_user.hospital_id:
            stmt = stmt.where(Appointment.hospital_id == current_user.hospital_id)
            
    results = (await db.execute(stmt)).all()
    
    appts = []
    for appt, patient, doctor, dept in results:
        appts.append({
            "id": appt.id,
            "patient_id": patient.id,
            "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
            "patient_phone": patient.phone,
            "doctor_id": doctor.id,
            "doctor_name": f"Dr. {doctor.first_name} {doctor.last_name}",
            "department_name": dept.name,
            "appointment_datetime": appt.appointment_datetime.isoformat(),
            "reason": appt.reason,
            "payment_status": appt.payment_status,
            "status": appt.status
        })
    return appts

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


@router.get("/doctors", tags=["hospital"])
async def list_doctors(db: AsyncSession = Depends(get_db)):
    """Retrieves all active doctor listings with schedules and details."""
    from app.database.models.appointment import DoctorSchedule
    stmt = select(Doctor, Department).join(Department, Doctor.department_id == Department.id).where(Doctor.is_active == True)
    results = (await db.execute(stmt)).all()
    
    doctors_info = []
    for doc, dept in results:
        # Get schedules
        sched_stmt = select(DoctorSchedule).where(DoctorSchedule.doctor_id == doc.id)
        schedules = (await db.execute(sched_stmt)).scalars().all()
        
        # day of week list
        work_days = [s.day_of_week for s in schedules]
        
        # Timing representation in Hindi (Dynamic)
        timing_str = ""
        if schedules:
            from collections import defaultdict
            session_times = defaultdict(list)
            for s in schedules:
                time_range = f"{s.start_time.strftime('%I:%M %p').lstrip('0')} - {s.end_time.strftime('%I:%M %p').lstrip('0')}"
                session_times[time_range].append(s.day_of_week)
            
            parts = []
            for tr, days_list in session_times.items():
                days_list.sort()
                day_names_map = {1: "सोम", 2: "मंगल", 3: "बुध", 4: "गुरु", 5: "शुक्र", 6: "शनि", 7: "रवि"}
                if len(days_list) >= 5 and days_list == list(range(days_list[0], days_list[0] + len(days_list))):
                    days_str = f"{day_names_map.get(days_list[0])}–{day_names_map.get(days_list[-1])}"
                else:
                    days_str = ", ".join([day_names_map.get(d, str(d)) for d in days_list])
                parts.append(f"{days_str}, {tr}")
            timing_str = " | ".join(parts)
        else:
            # Fallback for seeded doctors
            timing_str = "सोम–शुक्र, 10:00 AM - 01:00 PM | 02:00 PM - 05:00 PM"
            work_days = [1, 2, 3, 4, 5]

        doctors_info.append({
            "id": doc.id,
            "hospital_id": doc.hospital_id,
            "department_id": doc.department_id,
            "department_name": dept.name,
            "first_name": doc.first_name,
            "last_name": doc.last_name,
            "email": doc.email,
            "phone": doc.phone,
            "license_number": doc.license_number,
            "is_active": doc.is_active,
            "opd_fees": doc.opd_fees,
            "timings": timing_str,
            "work_days": work_days
        })
    return doctors_info


# ==========================================
# LEAVES & STAFF CRUD MANAGEMENT
# ==========================================

from app.schemas.appointment import DoctorLeaveCreate, DoctorLeaveRead
from app.database.models.appointment import DoctorLeave

@router.post("/hospital/leaves", response_model=DoctorLeaveRead, tags=["hospital"])
async def create_doctor_leave(
    payload: DoctorLeaveCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Allows Doctor or Admin to register a date/range of leave."""
    import uuid
    hosp_id = current_user.hospital_id if current_user.hospital_id else "hosp_default"
    doc_stmt = select(Doctor).where(Doctor.id == payload.doctor_id)
    doctor = (await db.execute(doc_stmt)).scalar_one_or_none()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    
    if doctor.hospital_id != hosp_id and current_user.username != "super_admin":
        raise HTTPException(status_code=403, detail="Unauthorized hospital access")
    
    leave_id = str(uuid.uuid4())
    new_leave = DoctorLeave(
        id=leave_id,
        doctor_id=payload.doctor_id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        reason=payload.reason
    )
    db.add(new_leave)
    await db.commit()
    return new_leave


@router.get("/hospital/leaves", tags=["hospital"])
async def list_doctor_leaves(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Fetches all registered doctor leaves for the hospital."""
    hosp_id = current_user.hospital_id if current_user.hospital_id else "hosp_default"
    stmt = select(DoctorLeave, Doctor).join(Doctor, DoctorLeave.doctor_id == Doctor.id).where(Doctor.hospital_id == hosp_id)
    results = (await db.execute(stmt)).all()
    
    leaves_info = []
    for leave, doc in results:
        leaves_info.append({
            "id": leave.id,
            "doctor_id": doc.id,
            "doctor_name": f"Dr. {doc.first_name} {doc.last_name}",
            "start_date": leave.start_date.isoformat(),
            "end_date": leave.end_date.isoformat(),
            "reason": leave.reason,
            "created_at": leave.created_at.isoformat()
        })
    return leaves_info


@router.delete("/hospital/leaves/{leave_id}", tags=["hospital"])
async def delete_doctor_leave(
    leave_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cancels/deletes a doctor leave record."""
    hosp_id = current_user.hospital_id if current_user.hospital_id else "hosp_default"
    stmt = select(DoctorLeave).join(Doctor, DoctorLeave.doctor_id == Doctor.id).where(
        (DoctorLeave.id == leave_id) & (Doctor.hospital_id == hosp_id)
    )
    leave = (await db.execute(stmt)).scalar_one_or_none()
    if not leave:
        raise HTTPException(status_code=404, detail="Leave record not found or unauthorized")
    
    await db.delete(leave)
    await db.commit()
    return {"status": "success", "message": "Leave deleted successfully"}


@router.delete("/hospital/staff/{user_id}", tags=["hospital"])
async def delete_staff_member(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Allows Hospital Admin to delete a staff member (Doctor or Receptionist) by user ID or Doctor ID."""
    role_stmt = select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == current_user.id)
    roles = (await db.execute(role_stmt)).scalars().all()
    if "ADMIN" not in roles and "SUPER_ADMIN" not in roles:
        raise HTTPException(status_code=403, detail="Unauthorized")
        
    hosp_id = current_user.hospital_id if current_user.hospital_id else "hosp_default"
    
    # 1. Check if user_id refers to a Doctor
    doc_stmt = select(Doctor).where((Doctor.id == user_id) & (Doctor.hospital_id == hosp_id))
    doctor = (await db.execute(doc_stmt)).scalar_one_or_none()
    
    if doctor:
        user_stmt = select(User).where((User.email == doctor.email) & (User.hospital_id == hosp_id))
        staff_user = (await db.execute(user_stmt)).scalar_one_or_none()
        await db.delete(doctor)
        if staff_user:
            await db.delete(staff_user)
    else:
        # 2. Fallback to direct User ID lookup
        user_stmt = select(User).where((User.id == user_id) & (User.hospital_id == hosp_id))
        staff_user = (await db.execute(user_stmt)).scalar_one_or_none()
        if not staff_user:
            raise HTTPException(status_code=404, detail="Staff member not found under this hospital")
            
        doc_stmt2 = select(Doctor).where(Doctor.email == staff_user.email)
        doctor2 = (await db.execute(doc_stmt2)).scalar_one_or_none()
        if doctor2:
            await db.delete(doctor2)
            
        await db.delete(staff_user)
        
    await db.commit()
    return {"status": "success", "message": "Staff member deleted successfully"}


@router.put("/hospital/staff/doctor/{doctor_id}", tags=["hospital"])
async def update_doctor_profile(
    doctor_id: str,
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    license_number: str = Form(...),
    opd_fees: int = Form(500),
    schedule_days: str = Form(...),
    schedule_start_time: str = Form(...),
    schedule_end_time: str = Form(...),
    schedule_start_time_2: Optional[str] = Form(None),
    schedule_end_time_2: Optional[str] = Form(None),
    slot_duration_minutes: int = Form(30),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Updates doctor details and rebuilds their schedules."""
    role_stmt = select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == current_user.id)
    roles = (await db.execute(role_stmt)).scalars().all()
    if "ADMIN" not in roles and "SUPER_ADMIN" not in roles:
        raise HTTPException(status_code=403, detail="Unauthorized")
        
    hosp_id = current_user.hospital_id if current_user.hospital_id else "hosp_default"
    
    doc_stmt = select(Doctor).where((Doctor.id == doctor_id) & (Doctor.hospital_id == hosp_id))
    doctor = (await db.execute(doc_stmt)).scalar_one_or_none()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")
        
    doctor.first_name = first_name
    doctor.last_name = last_name
    doctor.email = email
    doctor.phone = phone
    doctor.license_number = license_number
    doctor.opd_fees = opd_fees
    
    from app.database.models.appointment import DoctorSchedule
    del_stmt = select(DoctorSchedule).where(DoctorSchedule.doctor_id == doctor_id)
    old_scheds = (await db.execute(del_stmt)).scalars().all()
    for osc in old_scheds:
        await db.delete(osc)
        
    import uuid
    from datetime import time
    try:
        sh, sm = map(int, schedule_start_time.split(':'))
        eh, em = map(int, schedule_end_time.split(':'))
        t_start = time(sh, sm)
        t_end = time(eh, em)
        
        t_start_2, t_end_2 = None, None
        if schedule_start_time_2 and schedule_end_time_2:
            sh_2, sm_2 = map(int, schedule_start_time_2.split(':'))
            eh_2, em_2 = map(int, schedule_end_time_2.split(':'))
            t_start_2 = time(sh_2, sm_2)
            t_end_2 = time(eh_2, em_2)
            
        days = [int(d.strip()) for d in schedule_days.split(',') if d.strip().isdigit()]
        for day in days:
            s1 = DoctorSchedule(
                id=str(uuid.uuid4()),
                doctor_id=doctor.id,
                day_of_week=day,
                start_time=t_start,
                end_time=t_end,
                slot_duration_minutes=slot_duration_minutes
            )
            db.add(s1)
            if t_start_2 and t_end_2:
                s2 = DoctorSchedule(
                    id=str(uuid.uuid4()),
                    doctor_id=doctor.id,
                    day_of_week=day,
                    start_time=t_start_2,
                    end_time=t_end_2,
                    slot_duration_minutes=slot_duration_minutes
                )
                db.add(s2)
    except Exception as se:
        logger.error(f"Error rebuilding doctor schedule: {str(se)}")
        raise HTTPException(status_code=400, detail="Invalid schedule parameters")
        
    user_stmt = select(User).where(User.email == email)
    staff_user = (await db.execute(user_stmt)).scalar_one_or_none()
    if staff_user:
        staff_user.first_name = first_name
        staff_user.last_name = last_name
        
    await db.commit()
    return {"status": "success", "message": "Doctor profile updated successfully"}


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
    await auto_update_missed_appointments(db)

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
                Appointment.status.in_(["SCHEDULED", "PENDING_PAYMENT", "COMPLETED", "CANCELLED", "MISSED", "RESCHEDULED"])
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
        fees = f"₹{doc.opd_fees}" if (doc.opd_fees is not None) else fees_map.get(doc.id, "₹500")
        
        # Timing representation in Hindi (Dynamic)
        from app.database.models.appointment import DoctorSchedule
        sched_stmt = select(DoctorSchedule).where(DoctorSchedule.doctor_id == doc.id)
        doc_schedules = (await db.execute(sched_stmt)).scalars().all()
        if doc_schedules:
            from collections import defaultdict
            session_times = defaultdict(list)
            for s in doc_schedules:
                time_range = f"{s.start_time.strftime('%I:%M %p').lstrip('0')} - {s.end_time.strftime('%I:%M %p').lstrip('0')}"
                session_times[time_range].append(s.day_of_week)
            
            parts = []
            for tr, days_list in session_times.items():
                days_list.sort()
                day_names_map = {1: "सोम", 2: "मंगल", 3: "बुध", 4: "गुरु", 5: "शुक्र", 6: "शनि", 7: "रवि"}
                if len(days_list) >= 5 and days_list == list(range(days_list[0], days_list[0] + len(days_list))):
                    days_str = f"{day_names_map.get(days_list[0])}–{day_names_map.get(days_list[-1])}"
                else:
                    days_str = ", ".join([day_names_map.get(d, str(d)) for d in days_list])
                parts.append(f"{days_str}, {tr}")
            timing_str = " | ".join(parts)
        else:
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
        # Load intake info for this appointment (if exists)
        from app.database.models.appointment import PatientIntake
        intake_stmt = select(PatientIntake).where(PatientIntake.appointment_id == appt.id)
        intake_obj = (await db.execute(intake_stmt)).scalar_one_or_none()
        intake_html_parts = []
        if intake_obj:
            if intake_obj.has_visited_before is not None:
                intake_html_parts.append(f"🔁 पहले दिखाया: {'हाँ — ' + (intake_obj.previous_doctor or '') if intake_obj.has_visited_before else 'नहीं'}")
            if intake_obj.has_reports is not None:
                intake_html_parts.append(f"📄 Reports: {'हाँ — ' + (intake_obj.report_details or '') if intake_obj.has_reports else 'नहीं'}")
            if intake_obj.current_medicines:
                intake_html_parts.append(f"💊 दवाइयाँ: {intake_obj.current_medicines}")
            if intake_obj.additional_notes:
                intake_html_parts.append(f"📝 नोट: {intake_obj.additional_notes}")

        key = (f"Dr. {doctor.first_name} {doctor.last_name}", dept.name)
        by_doctor[key].append({
            "appointment_id": appt.id,
            "doctor_id": doctor.id,
            "time": appt.appointment_datetime.strftime("%I:%M %p"),
            "time_24": appt.appointment_datetime.strftime("%H:%M"),
            "appointment_datetime_iso": appt.appointment_datetime.isoformat(),
            "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
            "patient_phone": patient.phone,
            "reason": appt.reason or "—",
            "status": appt.status,
            "intake_html": "<br>".join(intake_html_parts) if intake_html_parts else "",
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
                appt_id = a['appointment_id']
                status = a['status']
                # Status badge
                badge_map = {
                    'SCHEDULED': '<span class="badge confirmed">✅ Confirmed</span>',
                    'PENDING_PAYMENT': '<span class="badge pending-pay">⏳ Payment Pending</span>',
                    'COMPLETED': '<span class="badge completed">🎉 Completed</span>',
                    'CANCELLED': '<span class="badge cancelled">❌ Cancelled</span>',
                    'MISSED': '<span class="badge missed">🚫 Missed</span>',
                    'RESCHEDULED': '<span class="badge rescheduled">📅 Rescheduled</span>',
                }
                badge = badge_map.get(status, f'<span class="badge">{status}</span>')

                # Status action buttons (only for actionable statuses)
                action_btns = ""
                if status in ["SCHEDULED", "PENDING_PAYMENT", "RESCHEDULED"]:
                    # Do not show Reschedule if payment is pending
                    reschedule_btn = f"""<button class="act-btn blue" onclick="openReschedule('{appt_id}', '{a["doctor_id"]}', '{status}')">📅 Reschedule</button>""" if status != "PENDING_PAYMENT" else ""
                    
                    action_btns = f"""
                    <div class="action-btns" id="actions-{appt_id}">
                        <button class="act-btn green" onclick="updateStatus('{appt_id}', 'COMPLETED', '{status}')">✅ Completed</button>
                        <button class="act-btn red" onclick="updateStatus('{appt_id}', 'CANCELLED', '{status}')">❌ Cancel</button>
                        <button class="act-btn orange" onclick="updateStatus('{appt_id}', 'MISSED', '{status}')">🚫 Missed</button>
                        {reschedule_btn}
                    </div>"""

                # Intake info panel
                intake_panel = ""
                if a.get('intake_html'):
                    intake_panel = f"""<div class="intake-panel"><span class="intake-label">🩺 AI Intake:</span> {a['intake_html']}</div>"""

                rows += f"""
                <tr class="appt-row" id="row-{appt_id}">
                    <td class="td-sno">{i}</td>
                    <td class="td-time">
                        <span class="time-pill">{a["time"]}</span>
                    </td>
                    <td class="td-patient">
                        <div class="patient-name">{a["patient_name"]}</div>
                        {intake_panel}
                    </td>
                    <td class="td-phone">
                        <a href="tel:{a["patient_phone"]}" class="phone-link">📞 {a["patient_phone"]}</a>
                    </td>
                    <td class="td-reason">{a["reason"]}</td>
                    <td class="td-status">
                        <div id="badge-{appt_id}">{badge}</div>
                        {action_btns}
                    </td>
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
                                <th>स्थिति / कार्रवाई</th>
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

        /* ── STATUS ACTION BUTTONS ── */
        .action-btns {{
            display: flex;
            flex-wrap: wrap;
            gap: 5px;
            margin-top: 8px;
        }}
        .act-btn {{
            padding: 4px 9px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 700;
            border: none;
            cursor: pointer;
            transition: all 0.15s;
            white-space: nowrap;
        }}
        .act-btn.green {{ background: #dcfce7; color: #15803d; }}
        .act-btn.green:hover {{ background: #bbf7d0; }}
        .act-btn.red {{ background: #fee2e2; color: #b91c1c; }}
        .act-btn.red:hover {{ background: #fecaca; }}
        .act-btn.orange {{ background: #fff7ed; color: #c2410c; }}
        .act-btn.orange:hover {{ background: #fed7aa; }}
        .act-btn.blue {{ background: #dbeafe; color: #1d4ed8; }}
        .act-btn.blue:hover {{ background: #bfdbfe; }}

        /* ── EXTRA STATUS BADGES ── */
        .badge.completed {{ background: #dcfce7; color: #15803d; }}
        .badge.cancelled {{ background: #fee2e2; color: #b91c1c; }}
        .badge.missed {{ background: #fef3c7; color: #92400e; }}
        .badge.rescheduled {{ background: #ede9fe; color: #6d28d9; }}

        /* ── AI INTAKE PANEL ── */
        .intake-panel {{
            margin-top: 6px;
            background: #f0f9ff;
            border: 1px solid #bae6fd;
            border-radius: 7px;
            padding: 6px 10px;
            font-size: 11.5px;
            color: #0369a1;
            line-height: 1.6;
        }}
        .intake-label {{
            font-weight: 700;
            display: block;
            margin-bottom: 2px;
        }}

        /* ── RESCHEDULE MODAL ── */
        .modal-overlay {{
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(15,50,118,0.45);
            z-index: 9000;
            align-items: center;
            justify-content: center;
        }}
        .modal-overlay.open {{ display: flex; }}
        .modal-box {{
            background: white;
            border-radius: 18px;
            padding: 32px;
            max-width: 460px;
            width: 95%;
            box-shadow: 0 20px 60px rgba(15,50,118,0.25);
        }}
        .modal-title {{ font-size: 18px; font-weight: 800; color: var(--primary-dark); margin-bottom: 20px; }}
        .modal-label {{ font-size: 13px; font-weight: 600; color: var(--text-muted); margin-bottom: 6px; }}
        .modal-input {{
            width: 100%;
            padding: 10px 14px;
            border: 1.5px solid var(--border);
            border-radius: 9px;
            font-size: 14px;
            margin-bottom: 16px;
            font-family: inherit;
        }}
        .modal-input:focus {{ outline: none; border-color: var(--primary); }}
        .modal-actions {{ display: flex; gap: 10px; justify-content: flex-end; margin-top: 8px; }}
        .modal-btn {{
            padding: 10px 20px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 700;
            border: none;
            cursor: pointer;
            transition: background 0.15s;
        }}
        .modal-btn.confirm {{ background: var(--primary); color: white; }}
        .modal-btn.confirm:hover {{ background: var(--primary-dark); }}
        .modal-btn.cancel {{ background: #f1f5f9; color: var(--text-muted); }}
        .modal-btn.cancel:hover {{ background: #e2e8f0; }}
    </style>
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
                <div style="display: flex; align-items: center; gap: 12px;">
                    <div class="header-logo" style="width: 40px; height: 40px; font-size: 20px; background: var(--primary-light); color: var(--primary); cursor: pointer; border: 1.5px solid var(--border); display: flex; align-items: center; justify-content: center; border-radius: 10px;" onclick="document.getElementById('date-select').showPicker()">📅</div>
                    <div>
                        <div class="date-text" style="display: flex; align-items: center; gap: 6px; cursor: pointer; color: var(--primary-dark); font-weight: 700; font-size: 17px;" onclick="document.getElementById('date-select').showPicker()">
                            {day_display} {today_flag}
                            <span style="font-size: 11px; color: var(--accent); vertical-align: middle;">▼</span>
                        </div>
                        <div class="day-text">{day_name}</div>
                    </div>
                    <!-- Hidden native date input triggered by calendar click -->
                    <input type="date" id="date-select" value="{target_date.isoformat()}" 
                           style="opacity: 0; width: 0; height: 0; position: absolute;"
                           onchange="window.location.href='/receptionist/schedule?hospital_id={hospital_id}&date_str=' + this.value">
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
            अंतिम अपडेट: {datetime.now().strftime("%d %b %Y, %I:%M:%S %p")}
        </div>
    </div>

    <!-- Reschedule Modal -->
    <div class="modal-overlay" id="rescheduleModal">
        <div class="modal-box">
            <div class="modal-title">📅 Appointment Reschedule करें</div>
            <input type="hidden" id="modal-appt-id">
            <input type="hidden" id="modal-doctor-id">
            <label class="modal-label">नई Date और Time:</label>
            <input type="datetime-local" class="modal-input" id="modal-new-datetime" onchange="fetchBusySlots()">
            
            <!-- Booked Slots list container -->
            <div id="busy-slots-container" style="display:none; margin-bottom: 16px;">
                <label class="modal-label" style="color: #b91c1c; display: flex; align-items: center; gap: 4px;">
                    🚫 व्यस्त स्लॉट्स (Already Booked Times):
                </label>
                <div id="busy-slots-list" style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px;"></div>
            </div>

            <label class="modal-label">मरीज़ के लिए पहुँचने की Cutoff Note (optional):</label>
            <input type="text" class="modal-input" id="modal-cutoff" placeholder="जैसे: कृपया 10 बजे तक पहुँचें">
            <div class="modal-actions">
                <button class="modal-btn cancel" onclick="closeReschedule()">रद्द करें</button>
                <button class="modal-btn confirm" onclick="confirmReschedule()">📅 Reschedule करें</button>
            </div>
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

        // Update appointment status (Completed / Cancelled / Missed)
        async function updateStatus(apptId, newStatus, currentStatus) {{
            const label = {{COMPLETED: 'Completed ✅', CANCELLED: 'Cancelled ❌', MISSED: 'Missed 🚫'}}[newStatus] || newStatus;
            
            let cancelReason = null;
            if (newStatus === 'CANCELLED' && currentStatus === 'SCHEDULED') {{
                cancelReason = prompt("इस Paid Appointment को निरस्त करने का कारण (Reason) दर्ज करें (यह मरीज़ को WhatsApp रिफंड सूचना के साथ भेजा जाएगा):");
                if (cancelReason === null) return; // user cancelled prompt
                if (!cancelReason.trim()) cancelReason = "अस्पताल के अनुरोध पर";
            }}

            if (!confirm(`क्या आप इस appointment को "${{label}}" mark करना चाहते हैं?`)) return;

            const formData = new FormData();
            formData.append('new_status', newStatus);
            if (cancelReason) {{
                formData.append('cancellation_reason', cancelReason);
            }}

            try {{
                const res = await fetch(`/appointments/${{apptId}}/status`, {{
                    method: 'POST',
                    body: formData
                }});
                const data = await res.json();
                if (data.success) {{
                    const badgeMap = {{
                        COMPLETED: '<span class="badge completed">🎉 Completed</span>',
                        CANCELLED: '<span class="badge cancelled">❌ Cancelled</span>',
                        MISSED: '<span class="badge missed">🚫 Missed</span>',
                    }};
                    document.getElementById(`badge-${{apptId}}`).innerHTML = badgeMap[newStatus] || newStatus;
                    const actionsDiv = document.getElementById(`actions-${{apptId}}`);
                    if (actionsDiv) actionsDiv.remove();
                    if (newStatus === 'CANCELLED' && currentStatus === 'SCHEDULED') {{
                        alert('✅ Appointment निरस्त कर दी गई है और मरीज़ को रिफंड की सूचना WhatsApp कर दी गई है।');
                    }}
                }} else {{
                    alert('कुछ गड़बड़ हो गई। दोबारा कोशिश करें।');
                }}
            }} catch (e) {{
                alert('Network error. Please try again.');
            }}
        }}

        // Open reschedule modal
        function openReschedule(apptId, doctorId, currentStatus) {{
            if (currentStatus === 'PENDING_PAYMENT') {{
                alert('❌ भुगतान अपूर्ण है (Payment Pending)। रीशेड्यूल केवल भुगतान पूरा होने के बाद ही संभव है।');
                return;
            }}

            document.getElementById('modal-appt-id').value = apptId;
            document.getElementById('modal-doctor-id').value = doctorId;
            
            const dtInput = document.getElementById('modal-new-datetime');
            dtInput.value = '';
            
            const now = new Date();
            const tzOffset = now.getTimezoneOffset() * 60000;
            const minDt = new Date(now.getTime() - tzOffset).toISOString().slice(0, 16);
            const maxDate = new Date(now.getTime() + 2 * 24 * 60 * 60 * 1000);
            const maxDt = new Date(maxDate.getTime() - tzOffset).toISOString().slice(0, 16);
            
            dtInput.min = minDt;
            dtInput.max = maxDt;
            
            document.getElementById('modal-cutoff').value = '';
            
            // Hide busy slots list
            document.getElementById('busy-slots-container').style.display = 'none';
            document.getElementById('busy-slots-list').innerHTML = '';

            document.getElementById('rescheduleModal').classList.add('open');
        }}

        function closeReschedule() {{
            document.getElementById('rescheduleModal').classList.remove('open');
        }}

        // Fetch busy slots dynamically
        async function fetchBusySlots() {{
            const docId = document.getElementById('modal-doctor-id').value;
            const newDtVal = document.getElementById('modal-new-datetime').value;
            if (!newDtVal) return;

            // Extract date (YYYY-MM-DD)
            const dateStr = newDtVal.split('T')[0];

            try {{
                const res = await fetch(`/receptionist/booked-slots?doctor_id=${{docId}}&date_str=${{dateStr}}`);
                const data = await res.json();
                const container = document.getElementById('busy-slots-container');
                const list = document.getElementById('busy-slots-list');
                
                list.innerHTML = '';
                if (data.booked_slots && data.booked_slots.length > 0) {{
                    data.booked_slots.forEach(slot => {{
                        const badge = document.createElement('span');
                        badge.className = 'badge cancelled';
                        badge.style.fontSize = '11px';
                        badge.style.padding = '3px 8px';
                        badge.style.background = '#fee2e2';
                        badge.style.color = '#b91c1c';
                        badge.textContent = slot;
                        list.appendChild(badge);
                    }});
                    container.style.display = 'block';
                }} else {{
                    list.innerHTML = '<span style="font-size:11px;color:#16a34a">💡 इस दिन कोई अन्य बुकिंग नहीं है। सारे स्लॉट्स खाली हैं।</span>';
                    container.style.display = 'block';
                }}
            }} catch (e) {{
                console.error("Failed to fetch busy slots", e);
            }}
        }}

        // Confirm reschedule — calls backend and sends WhatsApp
        async function confirmReschedule() {{
            const apptId = document.getElementById('modal-appt-id').value;
            const newDt = document.getElementById('modal-new-datetime').value;
            const cutoff = document.getElementById('modal-cutoff').value;

            if (!newDt) {{
                alert('कृपया नई Date और Time चुनें।');
                return;
            }}

            const formData = new FormData();
            formData.append('new_status', 'RESCHEDULED');
            formData.append('new_datetime', newDt);
            formData.append('cutoff_note', cutoff);

            try {{
                const res = await fetch(`/appointments/${{apptId}}/status`, {{
                    method: 'POST',
                    body: formData
                }});
                
                if (res.status === 400) {{
                    const errData = await res.json();
                    if (errData.detail === 'appointment already rescheduled once') {{
                        alert('⚠️ यह अपॉइंटमेंट पहले ही 1 बार reschedule की जा चुकी है। इसे दोबारा reschedule नहीं किया जा सकता।');
                        closeReschedule();
                        return;
                    }}
                }}

                const data = await res.json();
                if (data.success) {{
                    closeReschedule();
                    document.getElementById(`badge-${{apptId}}`).innerHTML = '<span class="badge rescheduled">📅 Rescheduled</span>';
                    const actionsDiv = document.getElementById(`actions-${{apptId}}`);
                    if (actionsDiv) actionsDiv.remove(); // Only allow 1 reschedule, so remove actions
                    alert('✅ Reschedule हो गया! मरीज़ के WhatsApp पर नया समय भेज दिया गया है।');
                }} else {{
                    alert('कुछ गड़बड़ हो गई।');
                }}
            }} catch (e) {{
                alert('Network error. Please try again.');
            }}
        }}

        // Close modal on backdrop click
        document.getElementById('rescheduleModal').addEventListener('click', function(e) {{
            if (e.target === this) closeReschedule();
        }});
    </script>

</body>
</html>"""
    return HTMLResponse(content=html)



# ==========================================
# RAZORPAY INTEGRATION
# ==========================================

def get_razorpay_client():
    key_id = os.environ.get("RAZORPAY_KEY_ID", "")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
    if not key_id or not key_secret:
        return None
    return razorpay.Client(auth=(key_id, key_secret))

@router.post("/payment/create-order", tags=["payment"])
async def create_razorpay_order(req: PaymentOrderRequest, db: AsyncSession = Depends(get_db)):
    client = get_razorpay_client()
    if not client:
        # Fallback to simulated payment if keys not configured
        return {"simulated": True, "order_id": "sim_" + str(uuid.uuid4())}
        
    try:
        # Amount in paise
        order_data = {
            "amount": req.amount * 100, 
            "currency": "INR",
            "receipt": req.appointment_id[:40]
        }
        order = client.order.create(data=order_data)
        return {"simulated": False, "order_id": order["id"], "key_id": os.environ.get("RAZORPAY_KEY_ID")}
    except Exception as e:
        logger.error(f"Razorpay order creation failed: {e}")
        raise HTTPException(status_code=500, detail="Could not create payment order")

@router.post("/payment/verify", tags=["payment"])
async def verify_razorpay_payment(req: PaymentVerifyRequest, db: AsyncSession = Depends(get_db)):
    client = get_razorpay_client()
    if not client:
        # Simulated success
        pass
    else:
        try:
            client.utility.verify_payment_signature({
                'razorpay_order_id': req.razorpay_order_id,
                'razorpay_payment_id': req.razorpay_payment_id,
                'razorpay_signature': req.razorpay_signature
            })
        except razorpay.errors.SignatureVerificationError:
            raise HTTPException(status_code=400, detail="Invalid payment signature")
        except Exception as e:
            logger.error(f"Razorpay verification failed: {e}")
            raise HTTPException(status_code=500, detail="Payment verification failed")
            
    # Payment verified successfully! Update appointment status
    from app.database.models.appointment import Appointment, AppointmentStatusHistory
    stmt = select(Appointment).where(Appointment.id == req.appointment_id)
    appointment = (await db.execute(stmt)).scalar_one_or_none()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
        
    if appointment.status == "PENDING_PAYMENT":
        history = AppointmentStatusHistory(
            id=str(uuid.uuid4()),
            appointment_id=appointment.id,
            previous_status="PENDING_PAYMENT",
            new_status="SCHEDULED",
            change_reason="Payment successful via Razorpay"
        )
        appointment.status = "SCHEDULED"
        db.add(history)
        await db.commit()
        
    return {"status": "success", "message": "Payment verified and appointment confirmed"}


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

    <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
    <script>
        async function processPayment() {{
            const btn = document.getElementById('payBtn');
            btn.disabled = true;
            btn.textContent = '🔄 Order बन रहा है...';

            try {{
                // Step 1: Create Razorpay Order on backend
                const orderRes = await fetch('/payment/create-order?appt={appointment.id}', {{
                    method: 'POST'
                }});
                const orderData = await orderRes.json();

                if (orderData.already_paid) {{
                    document.body.innerHTML = `<div style="text-align:center;padding:60px;font-family:Inter,sans-serif"><div style="font-size:56px">🎉</div><h2 style="color:#0f3276">पेमेंट पहले हो चुका है!</h2><p style="color:#64748b">आपकी अपॉइंटमेंट पहले से Confirmed है।</p></div>`;
                    return;
                }}

                // Step 2: Open Razorpay Checkout Modal
                const options = {{
                    key: orderData.key_id,
                    amount: orderData.amount,
                    currency: orderData.currency,
                    name: 'CP Tiwari Hospital',
                    description: 'OPD Appointment Fee',
                    handler: async function(response) {{
                        // Step 3: Verify payment on backend
                        const formData = new FormData();
                        if (response.razorpay_order_id) {{
                            formData.append('razorpay_order_id', response.razorpay_order_id);
                        }}
                        formData.append('razorpay_payment_id', response.razorpay_payment_id);
                        if (response.razorpay_signature) {{
                            formData.append('razorpay_signature', response.razorpay_signature);
                        }}
                        formData.append('appointment_id', '{appointment.id}');

                        const verifyRes = await fetch('/payment/verify', {{
                            method: 'POST',
                            body: formData
                        }});
                        const verifyData = await verifyRes.json();

                        if (verifyData.success) {{
                            document.body.innerHTML = `
                                <div style="display:flex;align-items:center;justify-content:center;min-height:100vh;background:#f0f5fc;font-family:Inter,sans-serif">
                                    <div style="background:white;max-width:440px;width:100%;padding:40px;border-radius:16px;box-shadow:0 10px 30px rgba(15,50,118,0.12);text-align:center">
                                        <div style="font-size:56px;margin-bottom:20px">🎉</div>
                                        <h2 style="font-size:22px;font-weight:800;color:#0f3276;margin-bottom:12px">भुगतान सफल रहा!</h2>
                                        <p style="color:#64748b;font-size:14px;line-height:1.6;margin-bottom:24px">
                                            आपका भुगतान सफलतापूर्वक प्राप्त हो गया है।<br>
                                            आपकी अपॉइंटमेंट अब <b>Confirmed</b> है।<br><br>
                                            💬 <b>थोड़ी देर में हमारी AI assistant आपको WhatsApp पर message करेगी</b> और Doctor से मिलने से पहले कुछ जानकारी लेगी।<br><br>
                                            पूरी जानकारी आपके WhatsApp पर भी भेज दी गई है।
                                        </p>
                                        <a href="/receptionist/schedule" style="display:inline-block;background:#0f3276;color:white;padding:12px 24px;border-radius:10px;text-decoration:none;font-weight:600;font-size:14px">डैशबोर्ड पर जाएं</a>
                                    </div>
                                </div>`;
                        }} else {{
                            alert('भुगतान verification असफल। कृपया support से संपर्क करें।');
                            btn.disabled = false;
                            btn.textContent = '🔒 भुगतान करें (Pay ₹{amount})';
                        }}
                    }},
                    prefill: {{
                        name: '{patient.first_name} {patient.last_name}',
                        contact: '{patient.phone}'
                    }},
                    theme: {{ color: '#1a4fa0' }},
                    modal: {{
                        ondismiss: function() {{
                            btn.disabled = false;
                            btn.textContent = '🔒 भुगतान करें (Pay ₹{amount})';
                        }}
                    }}
                }};

                if (orderData.order_id) {{
                    options.order_id = orderData.order_id;
                }}

                const rzp = new Razorpay(options);
                rzp.open();

            }} catch (err) {{
                console.error(err);
                alert('तकनीकी त्रुटि। नेटवर्क की जांच करें।');
                btn.disabled = false;
                btn.textContent = '🔒 भुगतान करें (Pay ₹{amount})';
            }}
        }}
    </script>

</body>
</html>"""
    return HTMLResponse(content=checkout_html)


# ==========================================
# RAZORPAY — CREATE ORDER
# ==========================================

@router.post("/payment/create-order", tags=["payment"])
async def create_razorpay_order(
    appt: str = Query(..., description="Appointment ID"),
    db: AsyncSession = Depends(get_db)
):
    """Creates a Razorpay Order and returns order_id + key_id to the frontend."""
    from app.database.models.appointment import Appointment, Doctor
    import razorpay

    stmt = select(Appointment).where(Appointment.id == appt)
    appointment = (await db.execute(stmt)).scalar_one_or_none()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found.")

    if appointment.status == "SCHEDULED":
        return {"already_paid": True}

    fees_map = {"doc_ortho": 500, "doc_cardio": 800, "doc_eye": 400}
    doctor_stmt = select(Doctor).where(Doctor.id == appointment.doctor_id)
    doctor = (await db.execute(doctor_stmt)).scalar_one_or_none()
    amount_inr = fees_map.get(appointment.doctor_id, 500)
    amount_paise = amount_inr * 100  # Razorpay uses paise

    # If secret is blank, don't request Order ID from Razorpay (use direct integration fallback)
    order_id = None
    if settings.RAZORPAY_KEY_SECRET:
        try:
            client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
            order_data = {
                "amount": amount_paise,
                "currency": "INR",
                "receipt": f"rcpt_{appointment.id[-8:]}",
                "notes": {
                    "appointment_id": appointment.id,
                    "doctor": appointment.doctor_id
                }
            }
            import asyncio as _asyncio
            order = await _asyncio.to_thread(client.order.create, data=order_data)
            order_id = order["id"]
        except Exception as e:
            logger.error(f"Razorpay order creation failed: {str(e)}")

    return {
        "order_id": order_id,
        "key_id": settings.RAZORPAY_KEY_ID,
        "amount": amount_paise,
        "amount_inr": amount_inr,
        "appointment_id": appointment.id,
        "currency": "INR"
    }


# ==========================================
# RAZORPAY — VERIFY PAYMENT & TRIGGER INTAKE
# ==========================================

@router.post("/payment/verify", tags=["payment"])
async def verify_razorpay_payment(
    razorpay_order_id: Optional[str] = Form(None),
    razorpay_payment_id: str = Form(...),
    razorpay_signature: Optional[str] = Form(None),
    appointment_id: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """Verifies Razorpay payment signature, marks appointment SCHEDULED, sends WhatsApp, and triggers AI intake call."""
    import razorpay
    import hmac
    import hashlib
    from app.database.models.appointment import Appointment, Patient, Doctor, AppointmentStatusHistory

    # 1. Verify digital signature if key secret is configured and signature/order details exist
    if settings.RAZORPAY_KEY_SECRET and razorpay_order_id and razorpay_signature:
        key_secret = settings.RAZORPAY_KEY_SECRET.encode()
        message = f"{razorpay_order_id}|{razorpay_payment_id}".encode()
        expected_sig = hmac.new(key_secret, message, hashlib.sha256).hexdigest()
        if expected_sig != razorpay_signature:
            raise HTTPException(status_code=400, detail="Payment signature verification failed.")
    else:
        logger.warning("Bypassing HMAC signature check because RAZORPAY_KEY_SECRET is not configured or direct payment was used.")

    # 2. Load appointment
    stmt = select(Appointment).where(Appointment.id == appointment_id)
    appointment = (await db.execute(stmt)).scalar_one_or_none()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found.")

    if appointment.status == "SCHEDULED":
        return {"success": True, "message": "Already confirmed"}

    # 3. Update appointment status
    old_status = appointment.status
    appointment.status = "SCHEDULED"
    appointment.updated_at = datetime.now()

    status_history = AppointmentStatusHistory(
        id=str(uuid.uuid4()),
        appointment_id=appointment.id,
        previous_status=old_status,
        new_status="SCHEDULED",
        change_reason=f"Razorpay payment verified. Payment ID: {razorpay_payment_id}"
    )
    db.add(status_history)
    await db.flush()

    # 4. Load patient and doctor
    patient_stmt = select(Patient).where(Patient.id == appointment.patient_id)
    patient = (await db.execute(patient_stmt)).scalar_one_or_none()
    doctor_stmt = select(Doctor).where(Doctor.id == appointment.doctor_id)
    doctor = (await db.execute(doctor_stmt)).scalar_one_or_none()

    await db.commit()

    # 5. Send payment confirmed WhatsApp to patient
    if patient and doctor:
        from app.services.whatsapp import WhatsAppNotificationService
        wa_service = WhatsAppNotificationService()
        wa_details = {
            "appointment_id": appointment.id,
            "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
            "patient_phone": patient.phone,
            "doctor_name": f"Dr. {doctor.first_name} {doctor.last_name}",
            "appointment_datetime": appointment.appointment_datetime.isoformat(),
            "reason": appointment.reason
        }
        asyncio.create_task(wa_service.send_payment_confirmation(wa_details))

        # 6. Start WhatsApp AI intake conversation after a short delay
        async def start_whatsapp_intake():
            await asyncio.sleep(5)  # 5 seconds after payment confirmation WhatsApp
            try:
                from app.services.whatsapp_intake import get_intake_service
                intake_svc = get_intake_service()
                await intake_svc.start_intake_conversation(
                    appointment_id=appointment.id,
                    patient_name=f"{patient.first_name} {patient.last_name}".strip(),
                    patient_phone=patient.phone,
                    doctor_name=f"Dr. {doctor.first_name} {doctor.last_name}",
                    appointment_datetime=appointment.appointment_datetime.isoformat()
                )
            except Exception as intake_err:
                logger.error(f"WhatsApp intake start failed (non-critical): {str(intake_err)}")

        asyncio.create_task(start_whatsapp_intake())

    return {
        "success": True,
        "message": "Payment verified. Appointment confirmed. WhatsApp intake conversation started.",
        "phone": patient.phone if patient else ""
    }


# ==========================================
# LEGACY — SIMULATED PAYMENT CONFIRM (kept for backward compat)
# ==========================================

@router.post("/payment/confirm/{appointment_id}", tags=["payment"])
async def payment_confirmation_webhook(
    appointment_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Simulated / test payment confirmation fallback.
    Updates appointment status to SCHEDULED and dispatches WhatsApp notification.
    """
    from app.database.models.appointment import Appointment, Patient, Doctor, AppointmentStatusHistory
    from app.services.whatsapp import WhatsAppNotificationService

    stmt = select(Appointment).where(Appointment.id == appointment_id)
    appointment = (await db.execute(stmt)).scalar_one_or_none()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found.")

    if appointment.status == "SCHEDULED":
        return {"success": True, "message": "Already confirmed", "phone": "N/A"}

    old_status = appointment.status
    appointment.status = "SCHEDULED"
    appointment.updated_at = datetime.now()

    status_history = AppointmentStatusHistory(
        id=str(uuid.uuid4()),
        appointment_id=appointment.id,
        previous_status=old_status,
        new_status="SCHEDULED",
        change_reason="Payment confirmed successfully via online portal"
    )
    db.add(status_history)
    await db.flush()

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
        asyncio.create_task(wa_service.send_payment_confirmation(wa_details))

    return {
        "success": True,
        "message": "Payment confirmed and WhatsApp dispatched.",
        "phone": patient.phone if patient else ""
    }


@router.post("/appointments/{appointment_id}/status", tags=["receptionist"])
async def update_appointment_status(
    appointment_id: str,
    new_status: str = Form(..., description="COMPLETED, CANCELLED, MISSED, or RESCHEDULED"),
    new_datetime: Optional[str] = Form(None, description="ISO datetime for RESCHEDULED status"),
    cutoff_note: Optional[str] = Form(None, description="Arrival cutoff instruction for patient"),
    cancellation_reason: Optional[str] = Form(None, description="Reason for cancellation (for refund WhatsApp)"),
    db: AsyncSession = Depends(get_db)
):
    """
    Receptionist action endpoint to update appointment status.
    On RESCHEDULED, updates time and sends WhatsApp to patient.
    """
    from app.database.models.appointment import Appointment, Patient, Doctor, AppointmentStatusHistory
    from app.services.whatsapp import WhatsAppNotificationService

    stmt = select(Appointment).where(Appointment.id == appointment_id)
    appointment = (await db.execute(stmt)).scalar_one_or_none()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found.")

    old_status = appointment.status

    # Validate reschedule rules
    if new_status == "RESCHEDULED":
        # 1. Payment completion check
        if old_status == "PENDING_PAYMENT":
            raise HTTPException(status_code=400, detail="payment not done reschedule not possible")
        
        # 2. Reschedule count check (limit: 1 time)
        history_check_stmt = select(AppointmentStatusHistory).where(
            and_(
                AppointmentStatusHistory.appointment_id == appointment_id,
                AppointmentStatusHistory.new_status == "RESCHEDULED"
            )
        )
        existing_reschedules = (await db.execute(history_check_stmt)).all()
        if len(existing_reschedules) >= 1:
            raise HTTPException(status_code=400, detail="appointment already rescheduled once")

        if not new_datetime:
            raise HTTPException(status_code=400, detail="New datetime required for rescheduling")

        try:
            appointment.appointment_datetime = datetime.fromisoformat(new_datetime)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid datetime format. Use ISO format.")

    appointment.status = new_status
    appointment.updated_at = datetime.now()

    history = AppointmentStatusHistory(
        id=str(uuid.uuid4()),
        appointment_id=appointment.id,
        previous_status=old_status,
        new_status=new_status,
        change_reason=f"Receptionist action: {new_status}"
    )
    db.add(history)
    await db.flush()

    patient_stmt = select(Patient).where(Patient.id == appointment.patient_id)
    patient = (await db.execute(patient_stmt)).scalar_one_or_none()
    doctor_stmt = select(Doctor).where(Doctor.id == appointment.doctor_id)
    doctor = (await db.execute(doctor_stmt)).scalar_one_or_none()

    await db.commit()

    # Send WhatsApp notification for reschedule
    if new_status == "RESCHEDULED" and patient and new_datetime:
        wa_service = WhatsAppNotificationService()
        wa_details = {
            "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
            "patient_phone": patient.phone,
            "doctor_name": f"Dr. {doctor.first_name} {doctor.last_name}" if doctor else "Doctor",
            "new_datetime": new_datetime,
            "cutoff_note": cutoff_note or ""
        }
        asyncio.create_task(wa_service.send_reschedule_notification(wa_details))

    # Send WhatsApp notification for missed appointment
    elif new_status == "MISSED" and patient:
        wa_service = WhatsAppNotificationService()
        wa_details = {
            "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
            "patient_phone": patient.phone,
            "doctor_name": f"Dr. {doctor.first_name} {doctor.last_name}" if doctor else "Doctor",
            "appointment_datetime": appointment.appointment_datetime.isoformat(),
            "reason": appointment.reason or "General consultation"
        }
        asyncio.create_task(wa_service.send_missed_notification(wa_details))

    # Send WhatsApp notification for cancellation (Refund info if paid)
    elif new_status == "CANCELLED" and patient:
        if old_status == "SCHEDULED":  # If they had paid, send refund notification
            wa_service = WhatsAppNotificationService()
            wa_details = {
                "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
                "patient_phone": patient.phone,
                "doctor_name": f"Dr. {doctor.first_name} {doctor.last_name}" if doctor else "Doctor",
                "appointment_datetime": appointment.appointment_datetime.isoformat(),
                "reason": cancellation_reason or "अस्पताल के अनुरोध पर"
            }
            asyncio.create_task(wa_service.send_cancellation_refund_notification(wa_details))

    return {"success": True, "appointment_id": appointment_id, "new_status": new_status}


@router.post("/appointments/{appointment_id}/complete", tags=["doctor"])
async def complete_consultation(
    appointment_id: str,
    clinical_notes: str = Form(..., description="Doctor's clinical summary/notes"),
    prescription: str = Form(..., description="Prescription medicines details"),
    follow_up_date: Optional[str] = Form(None, description="Follow-up date in YYYY-MM-DD format"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Saves consultation summary, writes prescription,
    transitions status to COMPLETED, and sends prescription details via WhatsApp.
    """
    from app.services.whatsapp import WhatsAppNotificationService

    # 1. Fetch user roles to verify authorization
    role_stmt = select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == current_user.id)
    roles = (await db.execute(role_stmt)).scalars().all()
    if "DOCTOR" not in roles and "ADMIN" not in roles:
        raise HTTPException(status_code=403, detail="Only Doctors or Admins can complete a consultation.")

    # 2. Fetch appointment details
    appt_stmt = select(Appointment).where(
        and_(
            Appointment.id == appointment_id,
            Appointment.hospital_id == current_user.hospital_id
        )
    )
    appt = (await db.execute(appt_stmt)).scalar_one_or_none()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found in this hospital.")

    old_status = appt.status
    if old_status == "COMPLETED":
        raise HTTPException(status_code=400, detail="Consultation already completed.")

    # 3. Transition status to COMPLETED
    appt.status = "COMPLETED"
    appt.updated_at = datetime.now()

    # 4. Save Status History
    history = AppointmentStatusHistory(
        id=str(uuid.uuid4()),
        appointment_id=appt.id,
        previous_status=old_status,
        new_status="COMPLETED",
        changed_by_user_id=current_user.id,
        change_reason="Consultation completed by doctor."
    )
    db.add(history)

    # 5. Parse follow-up date
    f_up_date = None
    if follow_up_date and follow_up_date.strip():
        try:
            f_up_date = datetime.strptime(follow_up_date.strip(), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format for follow_up_date. Use YYYY-MM-DD.")

    # 6. Save or Update ConsultationNote
    from app.database.models.appointment import ConsultationNote
    note_stmt = select(ConsultationNote).where(ConsultationNote.appointment_id == appointment_id)
    note = (await db.execute(note_stmt)).scalar_one_or_none()
    if not note:
        note = ConsultationNote(
            id=str(uuid.uuid4()),
            appointment_id=appointment_id,
            patient_id=appt.patient_id,
            doctor_id=appt.doctor_id,
            clinical_notes=clinical_notes,
            prescription=prescription,
            follow_up_date=f_up_date
        )
        db.add(note)
    else:
        note.clinical_notes = clinical_notes
        note.prescription = prescription
        note.follow_up_date = f_up_date

    await db.commit()

    # 7. Send WhatsApp Prescription details
    patient_stmt = select(Patient).where(Patient.id == appt.patient_id)
    patient = (await db.execute(patient_stmt)).scalar_one_or_none()
    
    doctor_stmt = select(Doctor).where(Doctor.id == appt.doctor_id)
    doctor = (await db.execute(doctor_stmt)).scalar_one_or_none()
    doc_name = f"Dr. {doctor.first_name} {doctor.last_name}" if doctor else "Doctor"

    hosp_stmt = select(Hospital).where(Hospital.id == appt.hospital_id)
    hospital = (await db.execute(hosp_stmt)).scalar_one_or_none()
    hosp_name = hospital.name if hospital else "Hospital"

    if patient and patient.phone:
        wa_service = WhatsAppNotificationService()
        wa_details = {
            "phone": patient.phone,
            "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
            "doctor_name": doc_name,
            "hospital_name": hosp_name,
            "clinical_notes": clinical_notes,
            "prescription": prescription,
            "follow_up_date": follow_up_date or "N/A"
        }
        asyncio.create_task(wa_service.send_prescription_notification(wa_details))

    return {
        "success": True,
        "message": "Consultation completed and prescription sent to patient.",
        "appointment_id": appointment_id
    }


# ==========================================
# RECEPTIONIST — FETCH BOOKED SLOTS API
# ==========================================

@router.get("/receptionist/booked-slots", tags=["receptionist"])
async def get_booked_slots(
    doctor_id: str = Query(...),
    date_str: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns a list of start times for all booked appointments of a doctor on a specific date.
    Used by the dashboard to show busy slots in RED inside the reschedule modal.
    """
    try:
        from datetime import date as date_type
        target_date = date_type.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    start_dt = datetime.combine(target_date, datetime.min.time())
    end_dt = datetime.combine(target_date, datetime.max.time())

    # Fetch active booked appointments (excluding cancelled)
    stmt = (
        select(Appointment)
        .where(
            and_(
                Appointment.doctor_id == doctor_id,
                Appointment.appointment_datetime >= start_dt,
                Appointment.appointment_datetime <= end_dt,
                Appointment.status.in_(["SCHEDULED", "PENDING_PAYMENT", "RESCHEDULED"])
            )
        )
    )
    appointments = (await db.execute(stmt)).scalars().all()
    booked_times = [appt.appointment_datetime.strftime("%I:%M %p") for appt in appointments]
    
    return {"booked_slots": booked_times}