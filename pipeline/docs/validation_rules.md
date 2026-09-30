# Validation rules

I profiled the raw file first (notebook section 2) and only wrote rules for problems that showed up or that
would break a metric. The rules live in `scripts/rules.py`. Counts are for the full file (110,527 rows) and come
from `outputs/validation_report.csv`.

Severity means:

- FAIL: the row can't be trusted as an appointment. It is excluded from every metric but stays in
  `fact_appointment` with `status = 'excluded'`.
- WARN: the appointment counts, but one field is suspect, so it is left out of the one metric that uses that field.
- INFO: recorded and counted. Nothing is excluded.

## Row-level rules

| ID | Rule | Severity | Rows | Business reason | Action |
|---|---|---|---|---|---|
| F01 | appointment date before the booking date | FAIL | 5 | a slot can't be booked after it happened; all 5 are no-shows, which suggests they are corrections, not visits | excluded |
| F02 | age below 0 | FAIL | 1 | not a real patient record | excluded |
| F03 | duplicate AppointmentID | FAIL | 0 | one slot would count twice | excluded (every copy) |
| F04 | No-show not Yes/No | FAIL | 0 | the outcome is the KPI | excluded |
| F05 | a 0/1 flag (incl. SMS_received) has another value | FAIL | 0 | SMS is the intervention; a bad value puts the row in the wrong group | excluded |
| W01 | age over 100 | WARN | 7 | possible but rare (max 115) | kept, left out of age breakdowns |
| W02 | PatientId has a decimal part | WARN | 5 | corrupted id, can't link the patient's history | kept, left out of the repeat no-show metric and the call list |
| W03 | SMS received but booked under 3 days ahead | WARN | 0 | against the sending pattern; would blur the eligible group | kept, not counted as eligible |
| I01 | Handcap is 2, 3 or 4 | INFO | 199 | the description says True/False; it's a count | none |
| I02 | weekend appointment | INFO | 39 | one Saturday (May 14) has appointments | none |
| I03 | same patient, several slots on one day | INFO | 16,200 | several slots in one visit | counted per slot (limitation) |
| I04 | age 0 | INFO | 3,539 | babies under 1, a real group | none |

After FAIL rules: 110,521 valid appointments and 6 excluded rows (0.005%).

Safe fixes (made in stage 2 on a copy; the raw file is never changed):

| Fix | Why it is safe |
|---|---|
| `PatientId` read as text, not as a number | as a number, ids become floats (`29872499824296.0`) that are awkward to join on and can't hold ids above 2^53 exactly; text keeps each id as written |
| `No-show` mapped once to `no_show` (1 = didn't come, 0 = came) | "No-show = Yes" is easy to read backwards; one mapping, tested, used everywhere |
| `ScheduledDay` and `AppointmentDay` parsed, the `Z` dropped, lead time counted in calendar days | no time is changed; `AppointmentDay` has no time of day, so days are the only honest unit |
| rows with an SMS but booked under 3 days ahead (W03) not counted as reminder-eligible | 0 rows today; stops a future bad row from blurring the SMS comparison |

What I chose not to do:

- I did not "fix" the 5 negative lead times by swapping dates. I don't know which date is wrong.
- I did not convert `ScheduledDay` from UTC. Booking hours run 06:00-21:00 with a peak at 07:00. If they were
  really UTC, the local peak would be 04:00, before clinics open. So I treat them as local time and record it
  as an assumption.
- I did not drop same-day bookings. They stay in the model and in the lead-time table. They are only left out
  of the KPI, for the reason in `metric_definitions.md`.
- I did not fill `SMS_received` on the outage days. The zeros are real: no SMS was received.

## File- and day-level checks (gates)

Stored in the `run_check` table and `outputs/run_checks.csv`. Stage 2 deletes its old output first, so stages
3 and 4 can't pick up a stale copy.

| Check | Stage | If it fails |
|---|---|---|
| a downloaded copy matches the pinned sha256 | stage1_retrieve | try the next copy; if none match, stop with exit 1 and leave the old file alone |
| local file matches the pinned sha256 on rerun | stage1_retrieve | download again (shown in `pipeline_run_log.txt`, run 3) |
| row count = 110,527 | stage1 / stage2 | stop, exit 1 |
| required columns present, no nulls | stage2_validate | FAIL, run held |
| FAIL rows at most 2% (change with `--max-fail-share`) | stage2_validate | FAIL, run held, exit 2 (run 4) |
| raw rows = valid + excluded | stage3_model | FAIL, run held |
| 100% of appointments join to `dim_date` and `dim_patient` | stage3_model | FAIL, run held |
| every weekday with no appointments is a public holiday | stage3_model | WARN: May 23 and May 27 are not explained |
| no appointment day has reminder coverage under 50% | stage3_model | WARN: 7 outage days, listed in the evidence table |
| weather covers every appointment day | stage3_model | WARN, rain check skipped |
| holiday / weather API reachable | stage1_retrieve | use the cached copy; if there is none, WARN and skip that check |

A HELD run keeps its row counts in `weekly_metrics.csv`, but the metric columns are blank and the pipeline
exits with code 2.
