# 🏥 Appointment Booking System – Final Database Schema

This document describes the **final, optimized database schema** for the doctor–patient appointment booking system. It is written to be **intuitive, implementation-ready, and scalable**.

---

## 🧠 High-Level Architecture

The system is divided into logical layers:

1. **Identity & Authentication** – Users, Devices, Refresh Tokens
2. **Domain Profiles** – Doctor, Patient
3. **Scheduling** – DoctorAvailability, DoctorSlots
4. **Business Transactions** – Appointment, Payment
5. **Communication** – Notifications

---

## 1️⃣ Users (`users`)

### Purpose

Central identity table for **authentication and authorization**.

| Column          | Type     | Key           | Description              |
| --------------- | -------- | ------------- | ------------------------ |
| id              | Integer  | PK            | Unique user identifier   |
| email           | String   | UNIQUE, INDEX | Login email              |
| name            | String   |               | Display name             |
| hashed_password | String   |               | Password hash            |
| role            | Enum     |               | DOCTOR / PATIENT / ADMIN |
| is_active       | Boolean  |               | Account status           |
| created_at      | DateTime |               | Created timestamp        |
| updated_at      | DateTime |               | Updated timestamp        |

**Relationships**

- 1 → 1 Doctor
- 1 → 1 Patient
- 1 → N Devices
- 1 → N Notifications

---

## 2️⃣ Doctor (`doctors`)

### Purpose

Doctor-specific professional and business information.

| Column                        | Type          | Key           | Description            |
| ----------------------------- | ------------- | ------------- | ---------------------- |
| id                            | Integer       | PK            | Doctor ID              |
| user_id                       | Integer       | FK (users.id) | Linked user            |
| speciality                    | String        | INDEX         | Medical specialization |
| opd_fees                      | Decimal(10,2) |               | Consultation fee       |
| minimum_slot_duration_minutes | Integer       |               | Slot length in minutes |
| latitude                      | Float         |               | Clinic latitude        |
| longitude                     | Float         |               | Clinic longitude       |
| address                       | String        |               | Clinic address         |
| created_at                    | DateTime      |               |                        |
| updated_at                    | DateTime      |               |                        |

**Relationships**

- 1 → N DoctorAvailability
- 1 → N DoctorSlots
- 1 → N Appointments

---

## 3️⃣ Patient (`patients`)

### Purpose

Patient-specific profile information.

| Column     | Type     | Key           | Description   |
| ---------- | -------- | ------------- | ------------- |
| id         | Integer  | PK            | Patient ID    |
| user_id    | Integer  | FK (users.id) | Linked user   |
| dob        | Date     |               | Date of birth |
| created_at | DateTime |               |               |
| updated_at | DateTime |               |               |

**Relationships**

- 1 → N Appointments

---

## 4️⃣ Device (`devices`)

### Purpose

Tracks user devices for **secure multi-device authentication**.

| Column        | Type     | Key                 | Description        |
| ------------- | -------- | ------------------- | ------------------ |
| id            | Integer  | PK                  | Device ID          |
| user_id       | Integer  | FK (users.id)       | Owner              |
| fingerprint   | String   | UNIQUE (user scope) | Device fingerprint |
| device_model  | String   |                     | Device info        |
| last_login_at | DateTime |                     | Last login time    |
| is_active     | Boolean  |                     | Device status      |
| created_at    | DateTime |                     |                    |
| updated_at    | DateTime |                     |                    |

**Relationships**

- 1 → N RefreshTokens

---

## 5️⃣ RefreshToken (`refresh_tokens`)

### Purpose

Secure session persistence with **token rotation**.

| Column     | Type     | Key             | Description          |
| ---------- | -------- | --------------- | -------------------- |
| id         | Integer  | PK              | Token ID             |
| user_id    | Integer  | FK (users.id)   | Owner                |
| device_id  | Integer  | FK (devices.id) | Issuing device       |
| token      | String   | INDEX           | Hashed refresh token |
| expires_at | DateTime |                 | Expiry time          |
| revoked    | Boolean  |                 | Revocation status    |
| created_at | DateTime |                 |                      |
| updated_at | DateTime |                 |                      |

---

## 6️⃣ DoctorAvailability (`doctor_availability`)

### Purpose

Defines **doctor working windows per day**.

| Column       | Type     | Key             | Description        |
| ------------ | -------- | --------------- | ------------------ |
| id           | Integer  | PK              | Availability ID    |
| doctor_id    | Integer  | FK (doctors.id) | Doctor             |
| date         | Date     |                 | Availability date  |
| start_time   | Time     |                 | Start time         |
| end_time     | Time     |                 | End time           |
| is_available | Boolean  |                 | Enabled / disabled |
| created_at   | DateTime |                 |                    |
| updated_at   | DateTime |                 |                    |

**Relationships**

- Many → 1 Doctor
- 1 → N DoctorSlots

---

## 7️⃣ DoctorSlots (`doctor_slots`)

### Purpose

Atomic **bookable time slots** derived from availability.

| Column     | Type     | Key                         | Description          |
| ---------- | -------- | --------------------------- | -------------------- |
| id         | Integer  | PK                          | Slot ID              |
| doctor_id  | Integer  | FK (doctors.id)             | Doctor               |
| avail_id   | Integer  | FK (doctor_availability.id) | Availability window  |
| date       | Date     |                             | Slot date            |
| start_time | Time     |                             | Slot start           |
| end_time   | Time     |                             | Slot end             |
| status     | Enum     |                             | FREE / HELD / BOOKED |
| created_at | DateTime |                             |                      |
| updated_at | DateTime |                             |                      |

---

## 8️⃣ Appointment (`appointments`)

### Purpose

Represents a **doctor–patient booking lifecycle**.

| Column     | Type     | Key                  | Description                            |
| ---------- | -------- | -------------------- | -------------------------------------- |
| id         | Integer  | PK                   | Appointment ID                         |
| doctor_id  | Integer  | FK (doctors.id)      | Doctor                                 |
| patient_id | Integer  | FK (patients.id)     | Patient                                |
| slot_id    | Integer  | FK (doctor_slots.id) | Reserved slot                          |
| status     | Enum     |                      | REQUESTED / APPROVED / REJECTED / PAID |
| report     | String   |                      | PDF / Image path                       |
| created_at | DateTime |                      |                                        |
| updated_at | DateTime |                      |                                        |

**Relationships**

- 1 → 1 Payment

---

## 9️⃣ Payment / Receipt (`payments`)

### Purpose

Handles **financial transactions** for appointments.

| Column         | Type          | Key                  | Description                |
| -------------- | ------------- | -------------------- | -------------------------- |
| id             | Integer       | PK                   | Payment ID                 |
| appointment_id | Integer       | FK (appointments.id) | Appointment                |
| stripe_id      | String        |                      | Stripe transaction ID      |
| amount         | Decimal(10,2) |                      | Paid amount                |
| currency       | String        |                      | Currency code              |
| status         | Enum          |                      | PENDING / SUCCESS / FAILED |
| created_at     | DateTime      |                      |                            |
| updated_at     | DateTime      |                      |                            |

**Relationship**

- 1 ↔ 1 Appointment

---

## 🔔 Notification (`notifications`)

### Purpose

User-facing **alerts and reminders**.

| Column     | Type     | Key           | Description                                |
| ---------- | -------- | ------------- | ------------------------------------------ |
| id         | Integer  | PK            | Notification ID                            |
| user_id    | Integer  | FK (users.id) | Recipient                                  |
| type       | Enum     |               | APPO_REQ / APPO_APPROVED / PAYMENT_SUCCESS |
| message    | String   |               | Notification text                          |
| is_read    | Boolean  |               | Read status                                |
| created_at | DateTime |               |                                            |

---

## ✅ Summary

✔ Clean separation of concerns
✔ Highly scalable scheduling model
✔ Secure authentication & payments
✔ Easy to extend (prescriptions, reviews, refunds)

This schema is **production-grade and future-proof**.
