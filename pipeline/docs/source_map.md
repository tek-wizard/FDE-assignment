# Source map

The client is hypothetical (the operations team of Vitoria's public clinics). All data is real and public.
**Data type: real online data only. Nothing is synthetic.**

## Business question -> information -> source

| # | Business question | Information needed | Source | Field(s) used |
|---|---|---|---|---|
| Q1 | How many booked slots are wasted, and is it getting better? | outcome per appointment, appointment date | S1 | `No-show`, `AppointmentDay` |
| Q2 | Do SMS reminders reduce no-shows? | reminder flag, lead time | S1 | `SMS_received`, `ScheduledDay`, `AppointmentDay` |
| Q3 | Did every reminder actually go out? | reminder flag per appointment day | S1 | `SMS_received` by `AppointmentDay` |
| Q4 | Is a missing day a holiday or a data gap? | public holidays | S2 | `date`, `name` |
| Q5 | Does rain explain bad days? | daily rain | S3 | `precipitation_sum` |
| Q6 | Is a small group of patients causing most no-shows? | patient id, outcome history | S1 | `PatientId`, `No-show` |

## Sources

| ID | Source | Owner | Grain | Retrieval mode | Source of truth for | Refresh |
|---|---|---|---|---|---|---|
| S1 | Appointment extract, `KaggleV2-May-2016.csv` (Kaggle "Medical Appointment No Shows", https://www.kaggle.com/datasets/joniarroba/noshowappointments, CC BY-NC-SA 4.0) | the clinics' scheduling system (in the real client: municipal IT) | one row per appointment | CSV file over HTTPS from public GitHub copies, accepted only if sha256 = `9132d3e7...` | appointments, bookings, SMS flag, outcome | one-off extract; a real client would send a weekly export |
| S2 | Nager.Date public holidays API, `/api/v3/PublicHolidays/2016/BR` | Nager.Date (open source) | one row per national holiday | JSON API | which weekdays are official holidays | yearly |
| S3 | Open-Meteo historical weather API, Vitoria (-20.32, -40.34) | Open-Meteo (ERA5 reanalysis) | one value per day | JSON API | daily rain and max temperature | daily |

Why these choices:

- **Kaggle is the original, but it needs a login**, which breaks a repeatable run. I found three public GitHub
  copies and checked they are byte-identical (same sha256). The pipeline tries them in order and refuses any copy
  whose checksum differs. So the source of truth is the checksum, not the URL.
- **The holidays API is used as a completeness check**, like a second system to reconcile against: every weekday
  with no appointments should be a holiday. May 26 (Corpus Christi) is; May 23 and May 27 are not.
- **Weather is there to test a common explanation.** Staff often blame bad days on rain. Rainy days (10 mm+) averaged
  18.9% no-show vs 20.3% on dry days. There were only 2 rainy days, which is too few to say anything either way.

## Key fields

| Field | Meaning | Problem found |
|---|---|---|
| `PatientId` | patient key | 5 ids have a decimal part (corrupted); read as text to keep all digits |
| `AppointmentID` | appointment key | unique (checked) |
| `ScheduledDay` | when the slot was booked | marked UTC, but hours match local clinic time |
| `AppointmentDay` | day of the slot | no time of day; 5 rows are before the booking date |
| `SMS_received` | 1 if the patient got at least one SMS | no send time, no delivery status; never 1 under 3 days lead |
| `No-show` | "Yes" = didn't come | the name is easy to read backwards; mapped once to `no_show = 1` |
| `Handcap` | disability | 0-4, not 0/1 as the description says |
| `Neighbourhood` | where the appointment is | 81 values; no clinic or doctor id |

## Missing data and events

| Missing | Why it matters | Who could give it |
|---|---|---|
| SMS send time and delivery status | can't tell "sent but not delivered" from "not sent" | SMS vendor logs |
| Phone number on file (yes/no) | may explain the ~18% of eligible patients with no SMS on normal days | patient register |
| Clinic, doctor, specialty | can't check capacity or specialty effects | scheduling system |
| Cancellations / rebooking events | a cancelled slot may look the same as a no-show | scheduling system |
| Appointment time of day | lead time only in days; morning vs afternoon unknown | scheduling system |
| Why May 9, 13, 16-20 had no SMS | outage vs data export gap | SMS vendor / IT |
| Why May 23 and 27 have no appointments | closure vs export gap | clinic managers |
