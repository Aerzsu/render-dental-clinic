# Dental Clinic Appointment System

## 🌟 About the project
The **Appointmenet System** is a full-stack web application developed to modernize the workflow of dental practitioners. It replaces manual scheduling with an automated, conflict-free booking engine and provides a centralized portal for patient records.

---

## 🛠️ Tech Stack
* **Backend:** Python 3.10+, Django 4.2 (MVC Architecture)
* **Frontend:** HTML5, CSS3, Tailwind CSS, JavaScript
* **Database:** PostgreSQL

---

## 🏗️ Project Architecture
The system is divided into high-cohesion apps to ensure maintainability:

```text
├── appointments/       # Slot generation and booking logic
├── core/               # Shared settings and utility functions
├── dental_clinic_project/ # Main project configuration
├── patient_portal/     # Client-facing dashboard and profile management
├── patients/           # CRUD operations for patient medical history
├── reports/            # Financial and clinical data visualization
├── services/           # Management of dental procedures and pricing
├── users/              # Custom user models and RBAC (Role Based Access Control)
├── build.sh            # Automated deployment script
└── render.yaml         # Infrastructure as Code for Render deployment
```

🚀 Key Features
**Intelligent Scheduling:** Prevents double-booking and manages clinic hours effectively.

**Patient Self-Service:** Patients can request appointments and view treatment history via the portal.

**Secure Authentication:** Distinct views and permissions for Admins, Staff, and Patients.

**Reporting & Analytics:** Generate summaries of clinic performance and patient demographics.

**Responsive Design:** Fully accessible via desktop, tablet, or mobile devices.
