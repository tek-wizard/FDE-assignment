# Stakeholders, KPI and scope

The client is hypothetical: I play the FDE for the operations team of the public clinics in Vitoria, Brazil.
The data is real: the public appointment extract (110,527 appointments, April to June 2016). I didn't interview
anyone. The goals and constraints below are what I would expect and would confirm in the first meeting.

## Who is affected and who owns the problem

| Stakeholder | Role in the problem | Goal | Constraint |
|---|---|---|---|
| Clinic operations manager (**owner**) | runs scheduling and the reminder process, reports to the health secretariat | fewer wasted slots without adding staff | fixed budget; can change process, not headcount |
| Reception / scheduling staff | book slots, take same-day walk-ins, would make reminder calls | a short list of who to call, not a report | about 10 minutes a day spare per desk (assumed) |
| Doctors and nurses | lose time when a booked patient doesn't come | a full clinic day | can't be double-booked without a rule for it |
| Patients | miss care, wait longer for the next slot | reminders they can act on, easy rebooking | about 10% are on the Bolsa Familia welfare program (`Scholarship`); phone access unknown |
| SMS vendor / municipal IT | sends the reminders | a clear sending rule and failure alerts | nobody watches daily send volume today (assumed) |
| Municipal health secretariat | funds the clinics | more patients seen for the same money | wants one number it can track |

## Facts, assumptions and unknowns

| Item | What I know or think | Status | How to confirm |
|---|---|---|---|
| Size | 110,527 appointments, 62,299 patients, 81 neighbourhoods, 27 appointment days | FACT (data) | row counts in the pipeline |
| No-show rate | 20.19% of all appointments, 28.52% of those booked 1+ days ahead | FACT (data) | metric KPI |
| Same-day bookings | 35% of rows, only 4.65% no-show | FACT (data) | lead-time table |
| Reminder rule | no SMS is ever sent if booked under 3 days ahead | FACT (pattern in the data), rule itself UNCONFIRMED | ask the SMS vendor for the sending rule |
| Reminder outage | 7 appointment days with 0% SMS coverage (May 9, 13, 16-20) | FACT (data), cause UNKNOWN | vendor send logs for those days |
| Missing days | May 23 and May 27 have no appointments; only May 26 is a public holiday | FACT (data), cause UNKNOWN | ask the clinic: closed, strike, or export gap? |
| Timestamps | marked UTC but match local clinic hours | ASSUMPTION | ask IT how `ScheduledDay` is stored |
| Neighbourhood | the place of the appointment, not where the patient lives | ASSUMPTION (Kaggle description) | ask IT |
| Why ~18% of eligible patients get no SMS on normal days | no phone number on file? | UNKNOWN | check the patient register |
| Cost of a no-show | not in the data | UNKNOWN | ask finance for cost per consultation |

## Problem statement

Around 3,500 advance-booked appointments a week end in a no-show (28.5%). The clinic believes the SMS reminder
doesn't work, because patients who got an SMS no-show more often than those who didn't. The clinic needs to know
whether reminders reduce no-shows, and whether the reminder process itself is reliable, before it drops, keeps or
extends them.

## Project KPI and supporting metrics

**Project KPI: no-show rate of appointments booked 1+ days ahead.** Lower is better. Same-day bookings are left out:
they are mostly walk-ins booked at the desk, they almost never no-show, and they would hide changes in the rate.

| # | Supporting metric | Why it matters for the KPI |
|---|---|---|
| S1 | Reminder coverage: share of eligible appointments (booked 3+ days ahead) that got an SMS | if the reminder isn't sent, it can't work; shows outages |
| S2 | Reminder effect at the same lead time: no-show points saved by an SMS | answers "do reminders work" at the same lead time, so the booking mix doesn't distort it |
| S3 | Share of no-shows from patients with 2+ no-shows in the window | shows if a small group causes a big part of the problem |
| S4 | Share of advance bookings made more than 14 days ahead | long lead times have the highest no-show rate |

Formulas and trigger levels: [metric_definitions.md](metric_definitions.md).

## MVP scope

What the MVP is: a repeatable weekly pipeline and evidence table that answers three questions: (1) do reminders
work, (2) did every reminder actually go out this week, and (3) who should get a phone call.

In scope:

- Retrieval of the extract (CSV) plus holidays and weather (APIs), with checksums and a manifest.
- Validation rules, a SQLite model, the KPI and 4 supporting metrics, weekly triggers, a dashboard.
- A daily reminder-coverage check that flags an outage day automatically.
- A weekly call list of patients with 2+ earlier no-shows (the operational output).
- A proposed test (below). The pipeline would measure it; running it needs the clinic.

Out of scope:

- A no-show prediction model or any machine learning.
- Overbooking rules, changes to the SMS text, a new SMS vendor.
- Patient-level outputs in the repo (the call list is written only to `data/processed/`, which is not committed).
- Cost figures (not in the data).

## What success means

For the MVP itself: the pipeline reruns and gives the same numbers, and every open question above has an owner.

For the clinic, a 4-week test after the MVP:

| Arm | Change |
|---|---|
| Control | current process |
| Treatment | fix outage monitoring (alert when a day's coverage is under 50%) + extend SMS to bookings 1-2 days ahead + a reception phone call for patients with 2+ earlier no-shows (about 3 calls per neighbourhood per day, from `call_list.csv`) |

Success: the KPI in Treatment is at least 2 points below Control (28.5% -> 26.5% or lower). Coverage stays above
80% every day. Guardrails: opt-out or complaint rate doesn't rise, and reception call time stays under 10 minutes
per desk per day.

Why 2 points: if every eligible appointment had been reminded in these 6 weeks, the measured 5.4-point effect on
the 24,539 appointments that weren't reminded is about 1,325 fewer no-shows, or 1.8 points on the KPI. So fixing
coverage alone should get close to 2 points. Anything more has to come from the 1-2 day SMS and the phone calls.
