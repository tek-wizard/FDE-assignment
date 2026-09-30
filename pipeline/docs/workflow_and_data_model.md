# Workflow and data model

## The current workflow

One appointment goes through these steps. The problem shows up at step 5, but the cause can be at step 1
(how far ahead the slot is booked) or step 3 (whether a reminder actually went out).

```mermaid
flowchart LR
    A[1. Patient books a slot<br/>at the desk or by phone] --> B[2. Slot saved in scheduling system<br/>ScheduledDay, AppointmentDay]
    B -->|booked 3+ days ahead| C[3. SMS reminder job<br/>SMS_received]
    B -->|booked 0-2 days ahead| D[no reminder]
    C --> E[4. Appointment day]
    D --> E
    E --> F{5. Patient comes?}
    F -->|yes| G[attended]
    F -->|no| H[no-show: slot wasted]
    H --> I[6. Rebook, maybe no-show again]
    I --> A
```

Plain-text version:

```
book (desk / phone)              <- lead time is decided here
  -> slot in scheduling system
  -> SMS reminder, only if booked 3+ days ahead   <- the intervention; failed on 7 days
  -> appointment day
  -> attended | no-show          <- the outcome (the KPI)
  -> rebook                      <- repeat no-shows come back here
```

Where the problem appears and what happens around it:

| Before | The problem | After |
|---|---|---|
| booking lead time (median 4 days, 38.6% of advance bookings 15+ days out); reminder sent or not | the patient doesn't come; 28.5% of advance-booked slots | slot is lost, doctor idle; patient rebooks later; 5% of patients cause 35% of no-shows |

## Entities, events, intervention, outcome

- Entities: patient, appointment (slot), neighbourhood (where the clinic is), calendar day.
- Events: booked (timestamp), reminder_sms (no timestamp in the source), attended or no_show (appointment date).
- Intervention: the SMS reminder. A second intervention is proposed: a reception phone call from the call list.
- Outcome: `no_show` per appointment, rolled up into the weekly KPI.
- Day-level context: public holiday (API), rain (API), reminder coverage and outage flag (computed).

## The relational model (SQLite, `data/processed/clinic.db`)

```mermaid
erDiagram
    dim_patient ||--o{ fact_appointment : "patient_id"
    dim_neighbourhood ||--o{ fact_appointment : "neighbourhood"
    dim_date ||--o{ fact_appointment : "appointment_date"
    fact_appointment ||--o{ appointment_flag : "appointment_id"
    validation_rule ||--o{ appointment_flag : "rule_id"
    fact_appointment ||--o{ appointment_event : "view: booked, reminder_sms, attended/no_show"

    fact_appointment {
        int appointment_id
        text patient_id FK
        text neighbourhood FK
        text booked_ts
        text appointment_date FK
        int lead_days
        text lead_band
        int sms_eligible "booked 3+ days ahead"
        int sms_received "the intervention"
        int no_show "the outcome"
        text status "valid / excluded"
    }
    dim_patient {
        text patient_id PK
        int id_ok "0 if the id is corrupted"
        int appointments
    }
    dim_date {
        text date PK
        text weekday
        text holiday_name "Nager.Date API"
        real precipitation_mm "Open-Meteo API"
        int eligible_valid
        int sms_valid
        real reminder_coverage
        int reminder_outage
    }
    dim_neighbourhood {
        text neighbourhood PK
        int appointments
    }
    validation_rule {
        text rule_id PK
        text severity
        text business_reason
    }
    appointment_flag {
        int appointment_id
        text rule_id FK
    }
```

Plain-text version:

```
dim_patient (1) ---< fact_appointment >--- (1) dim_date   [holiday + rain + reminder coverage per day]
                        |       \
                        |        >--- (1) dim_neighbourhood
                        +---< appointment_flag >--- validation_rule
fact_appointment (1) ---< appointment_event (view, 2 or 3 events per appointment)
run_check: file-level and day-level checks
```

Notes on the choices:

- The grain is the appointment (one slot). A patient with 3 slots on one day counts 3 times, because 3 slots
  were wasted. In 82% of those cases all slots share the same outcome.
- `fact_appointment` keeps the 6 excluded rows, so `raw = valid + excluded` can be checked in SQL.
- `reminder_outage` is on `dim_date`, not on the appointment, because the outage is a property of the day: it
  doesn't depend on the patient. That is what makes it usable as a fair comparison.
- Repeat no-shows use a window function over earlier days only (`RANGE ... 1 PRECEDING`), so a second slot on
  the same day doesn't count as history.
