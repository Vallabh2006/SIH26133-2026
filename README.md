
# Anvaya Vistara - Rural Healthcare Platform

## 1. Project Overview

Anvaya Vistara is an integrated multi-tiered healthcare management platform designed for rural health networks - Primary Health Centres (PHCs), Sub-Centres, and District Hospitals. It streamlines patient registration, OPD queue management, inter-hospital referral tracking, inventory control, electronic health records (EHR), teleconsultation, and secure authentication flows.

-   **General Login:**  `https://app.anvaya.site/login`
-   **Patient Signup:**  `https://app.anvaya.site/signup`
-   **Logout:**  `https://app.anvaya.site/logout`
-   **Forgot Password:**  `https://app.anvaya.site/forgot-password`
-   **Admin Portals:**  `https://app.anvaya.site/admin/`
-   **PHC Portals:**  `https://app.anvaya.site/phc/` 
-   **Patient Portal:**  `https://app.anvaya.site/patient/`  

### Key Features

- **OPD Queue & Token Management** - Triage-priority token generation (`OPD-001`, `EMG-001`, `REF-001`), queue status progression (`scheduled -> checked_in -> in_progress -> completed / no_show`), live public display board polling, and estimated wait time.
- **Inter-Hospital Referral Tracking** - Visual 5-stage referral stepper and 1-click priority destination queue auto-enqueue between PHCs, CHCs, and District Hospitals.
- **Teleconsultation** - Real-time text-based chat rooms between clinicians and patients with session management, message polling, diagnosis, and prescription on completion.
- **2-Step Password Reset & Privacy** - Masked email privacy protection (e.g. `va*****a@g***l.com`) and mandatory 2-step OTP verification before password creation.
- **Role-Based Access Control (RBAC)** - Configurable permission matrix across 11 roles and 15 action scopes, editable from the admin UI.
- **Audit Logging** - Every sensitive action is recorded with user ID, IP address, and timestamp for compliance.
- **Structured Logging** - Colored, formatted log output with per-module loggers and log-level control.
- **Rate Limiting & IP Security** - Per-endpoint rate limits via Flask-Limiter, IP lockout on repeated login failures, and optional VPN blocking.
- **Internationalization (i18n)** - Hindi (`hi`) and English (`en`) language support via JSON translation files.
- **Time Sync & Validation** - Server-side world clock endpoint (`/api/time`) for client synchronization and past-slot booking prevention.

---

## 2. Available Routes & Specifications

### I) Authentication & Account Recovery (`/` prefix)

| Route | Description |
|---|---|
| `/login` | Role-aware sign-in (username + password or email + OTP) |
| `/signup` | Patient self-registration with email OTP verification |
| `/verify-otp` | 6-digit OTP verification for signup and email login |
| `/accept-invite/<token>` | Staff invitation acceptance and password setup |
| `/forgot-password` | Account recovery with masked email privacy |
| `/reset-password/<token>` | OTP verification and new password creation |
| `/logout` | Secure session clearance with audit log |
| `/app` | Smart role-based redirect after login |

### II) Primary Health Centre - PHC (`/phc` prefix)

| Route | Description |
|---|---|
| `/phc/dashboard` | PHC operational overview for Medical Officers and staff |
| `/phc/queue` | Live triage priority queue and token management |
| `/phc/queue/display` | Public OPD queue display board (no auth required) |
| `/phc/consultation` | Clinical consultation - vitals, EHR, prescriptions |
| `/phc/teleconsult` | Teleconsultation session list and management |
| `/phc/teleconsult/room/<id>` | Real-time teleconsult chat room |
| `/phc/prescriptions` | Pharmacy prescription dispatch interface |
| `/phc/inventory` | Centre-level medical supply and vaccine stock control |
| `/phc/referrals` | Incoming and outgoing inter-hospital referrals |

### III) Regional & District Hospital (`/region` prefix)

| Route | Description |
|---|---|
| `/region/dashboard` | District hospital operational overview |
| `/region/referrals` | Incoming PHC transfer management |
| `/region/counter-referrals` | Specialist counter-referral guidance |
| `/region/admissions` | Patient ward admissions tracking |
| `/region/discharges` | Patient discharge summaries |

### IV) Administration (`/admin` prefix)

| Route | Description |
|---|---|
| `/admin/dashboard` | System administrator dashboard with live audit feed |
| `/admin/analytics` | Epidemiological analytics and disease tracking |
| `/admin/surveillance` | Health outbreak surveillance data |
| `/admin/facilities` | Healthcare facility directory and resource management |
| `/admin/inventory` | Global medical supply inventory with CSV import/export |
| `/admin/reports` | Aggregated health network report generation |
| `/admin/users` | Staff and patient account management |
| `/admin/staff` | Staff registration, invitations, and role management |
| `/admin/permissions` | RBAC role-action permission matrix configuration |
| `/admin/audit-logs` | System audit logs with CSV export |

### V) Patients (`/patient` prefix)

| Route | Description |
|---|---|
| `/patient/appointments` | Online OPD booking and live queue position tracker |
| `/patient/my_records` | Personal medical history, prescriptions, and labs |
| `/patient/teleconsult` | Patient teleconsultation portal |
| `/patient/map` | Interactive healthcare facility map |
| `/patient/facilities` | Facility directory for patients |
| `/patient/emergency` | Emergency contacts and ambulance request |
| `/patient/notifications` | Patient notification centre |

### VI) Facilities & Shared Pages

| Route | Description |
|---|---|
| `/facilities/` | Directory of all regional facilities |
| `/facilities/<facility_id>` | Specific facility details and capacity |
| `/map` | Regional interactive healthcare facility map |
| `/settings` | User profile settings, password change, email update |
| `/notifications` | Notification centre (role-aware redirect) |

### VII) JSON API (`/api` prefix)

| Route | Method | Description |
|---|---|---|
| `/api/health` | GET | Health check endpoint |
| `/api/time` | GET | Server time synchronization |
| `/api/notifications` | GET | Fetch user notifications (JSON) |
| `/api/notifications/read` | POST | Mark notifications as read |
| `/api/set-lang` | POST | Set language preference |

---

## 3. Configuration & Environment

Environment variables are loaded via `python-dotenv` from `.env`. See [`.env.example`](.env.example) for the full template.

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask session encryption key (**required**, app refuses to start without it) |
| `DB_TYPE` | Database backend (`postgres`) |
| `PG_HOST`, `PG_PORT`, `PG_USER`, `PG_PASSWORD`, `PG_DB` | PostgreSQL / Supabase connection |
| `SESSION_TYPE` | Session backend (`filesystem`) |
| `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER` | Mailjet API credentials and sender address |
| `RATELIMIT_ENABLED`, `RATELIMIT_DEFAULT` | Rate limiting toggle and default limits |
| `BLOCK_VPN` | Toggle VPN/proxy blocking on auth routes |
| `OTP_VALIDITY_SECONDS` | OTP expiry duration (default: 600s) |
| `FLASK_ENV` | `development` or `production` (controls debug mode, rate limits) |

---

## 4. Project Structure

```
Anvaya-Vistara/
│
├── .env
├── .env.example
├── app.py
├── config.py
├── requirements.txt
├── postgres_sample.sql
│
├── blueprints/
│   ├── admin/
│   ├── api/
│   ├── auth/
│   ├── center/
│   ├── dashboard/
│   ├── patient/
│   ├── phc/
│   └── region/
│
├── static/
│   ├── js/
│   │   └── main.js
│   └── styles.css
│
├── templates/
│   ├── admin/
│   ├── auth/
│   ├── center/
│   ├── dashboard/
│   ├── errors/
│   ├── facilities/
│   ├── patient/
│   ├── phc/
│   ├── region/
│   ├── base.html
│   └── shell.html
│
├── translations/
│   ├── en.json
│   └── hi.json
│
└── utils/
    ├── __init__.py
    ├── audit.py
    ├── auth_helpers.py
    ├── constants.py
    ├── db.py
    ├── defaults.py
    ├── email_helper.py
    ├── i18n.py
    ├── id_generator.py
    ├── logger.py
    ├── notifications.py
    ├── permissions.py
    ├── sanitize.py
    └── security.py
```

---

## 5. Technology Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.x, Flask 3.1 |
| **Database** | PostgreSQL (Supabase-hosted), psycopg2 |
| **Frontend** | HTML5, Vanilla CSS3, JavaScript |
| **Email** | Mailjet REST API |
| **Auth & Security** | bcrypt, Flask-Session, Flask-Limiter, Flask-WTF (CSRF), IP lockout |
| **Rate Limiting** | Flask-Limiter (in-memory or Redis-backed) |

---

## 6. Getting Started

### Prerequisites
- Python 3.10+
- PostgreSQL database (Supabase project)
- Mailjet account (for transactional email)

## 7. Dependencies

All packages are pinned in [`requirements.txt`](requirements.txt):

| Package | Purpose |
|---|---|
| `Flask` | Core web framework |
| `psycopg2-binary` | PostgreSQL database adapter |
| `Flask-Session` | Server-side filesystem session management |
| `Flask-Limiter` | IP and endpoint rate limiting |
| `Flask-WTF` + `WTForms` | Form validation and CSRF protection |
| `Flask-Cors` | Cross-Origin Resource Sharing |
| `bcrypt` | Secure password hashing |
| `mailjet-rest` | Transactional email delivery API |
| `python-dotenv` | `.env` file loading |
| `requests` | Outbound HTTP calls |
| `msgspec` | Fast serialization |
