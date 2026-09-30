"""Stage 3: build the relational model in SQLite and run the between-stage checks.

Tables (data/processed/clinic.db):
  dim_patient        one row per patient id
  dim_neighbourhood  one row per neighbourhood where appointments take place
  dim_date           one row per calendar day in the window: weekday, holiday, rain, reminder coverage
  fact_appointment   one row per raw appointment record (valid and excluded)
  appointment_flag   one row per (appointment, rule) that fired
  validation_rule    the rule catalogue
  run_check          file-level and day-level checks from stages 2 and 3
  appointment_event  view: booked, reminder_sms and outcome events of each appointment

The grain is the appointment (one booked slot). The source has no event log, so the events
come from the booking timestamp, the SMS flag and the outcome on each row.
"""
import json
import sqlite3

import pandas as pd

import common as c
import rules

SCHEMA = """
CREATE TABLE dim_patient (
    patient_id TEXT PRIMARY KEY,
    id_ok INTEGER NOT NULL,               -- 0 if the id has a decimal part (W02)
    appointments INTEGER NOT NULL
);
CREATE TABLE dim_neighbourhood (
    neighbourhood TEXT PRIMARY KEY,
    appointments INTEGER NOT NULL
);
CREATE TABLE dim_date (
    date TEXT PRIMARY KEY,
    weekday TEXT, is_weekday INTEGER,
    holiday_name TEXT,                    -- from the Nager.Date API, NULL if not a public holiday
    precipitation_mm REAL, temp_max_c REAL,  -- from Open-Meteo, NULL if the API was down
    appointments INTEGER NOT NULL,
    eligible_valid INTEGER NOT NULL,      -- valid appointments booked 3+ days ahead
    sms_valid INTEGER NOT NULL,
    reminder_coverage REAL,               -- sms / eligible, %
    reminder_outage INTEGER NOT NULL      -- 1 if coverage below the outage level
);
CREATE TABLE fact_appointment (
    appointment_id INTEGER NOT NULL,
    patient_id TEXT NOT NULL REFERENCES dim_patient(patient_id),
    neighbourhood TEXT NOT NULL REFERENCES dim_neighbourhood(neighbourhood),
    booked_ts TEXT NOT NULL,
    appointment_date TEXT NOT NULL REFERENCES dim_date(date),
    lead_days INTEGER NOT NULL,
    lead_band TEXT NOT NULL,
    sms_eligible INTEGER NOT NULL,
    sms_received INTEGER NOT NULL,
    no_show INTEGER,
    age INTEGER, gender TEXT, scholarship INTEGER,
    status TEXT NOT NULL                  -- valid / excluded
);
CREATE INDEX ix_fact_date ON fact_appointment(appointment_date);
CREATE INDEX ix_fact_patient ON fact_appointment(patient_id, appointment_date);
CREATE TABLE appointment_flag (
    appointment_id INTEGER NOT NULL,
    rule_id TEXT NOT NULL REFERENCES validation_rule(rule_id)
);
CREATE TABLE validation_rule (
    rule_id TEXT PRIMARY KEY, rule TEXT, severity TEXT, "check" TEXT, business_reason TEXT, action TEXT
);
CREATE TABLE run_check (
    scope TEXT, "check" TEXT, status TEXT, detail TEXT
);
CREATE VIEW appointment_event AS
    SELECT appointment_id, 'booked' AS event, booked_ts AS event_ts FROM fact_appointment
    UNION ALL
    -- the send time is not in the source, only that an SMS was received
    SELECT appointment_id, 'reminder_sms', NULL FROM fact_appointment WHERE sms_received = 1
    UNION ALL
    SELECT appointment_id, CASE no_show WHEN 1 THEN 'no_show' ELSE 'attended' END, appointment_date
    FROM fact_appointment WHERE no_show IS NOT NULL;
"""


def load_holidays():
    body = c.read_json(c.HOLIDAYS_JSON)
    if body is None:
        return None
    return {h["date"]: h["name"] for h in body if h.get("global", True)}


def load_weather():
    body = c.read_json(c.WEATHER_JSON)
    if body is None:
        return None
    d = body["daily"]
    return pd.DataFrame({"date": d["time"], "precipitation_mm": d["precipitation_sum"],
                         "temp_max_c": d["temperature_2m_max"]})


def build_dim_date(df, holidays, weather):
    days = pd.date_range(df["appointment_date"].min(), df["appointment_date"].max(), freq="D")
    dd = pd.DataFrame({"date": days.strftime("%Y-%m-%d")})
    dd["weekday"] = days.day_name()
    dd["is_weekday"] = (days.dayofweek < 5).astype(int)
    dd["holiday_name"] = dd["date"].map(holidays or {})

    d = df.assign(date=df["appointment_date"].dt.strftime("%Y-%m-%d"))
    valid = d[d["status"] == "valid"]
    elig = valid[(valid["sms_eligible"] == 1) & ~valid["W03"]]
    dd = dd.merge(d.groupby("date").size().rename("appointments"), on="date", how="left")
    dd = dd.merge(elig.groupby("date").size().rename("eligible_valid"), on="date", how="left")
    dd = dd.merge(elig.groupby("date")["SMS_received"].sum().rename("sms_valid"), on="date", how="left")
    for col in ["appointments", "eligible_valid", "sms_valid"]:
        dd[col] = dd[col].fillna(0).astype(int)
    dd["reminder_coverage"] = (100 * dd["sms_valid"] / dd["eligible_valid"]).where(dd["eligible_valid"] > 0).round(2)
    # a day with fewer than 50 eligible appointments (the one Saturday) is too small to call an outage
    dd["reminder_outage"] = ((dd["reminder_coverage"] < c.OUTAGE_COVERAGE_BELOW)
                             & (dd["eligible_valid"] >= 50)).astype(int)
    if weather is not None:
        dd = dd.merge(weather, on="date", how="left")
    else:
        dd["precipitation_mm"] = None
        dd["temp_max_c"] = None
    return dd


def main(log):
    c.parse_args("Stage 3: build the SQLite model")
    if not c.FLAGGED_PATH.exists():
        raise c.PipelineError("no flagged appointments found, run stage2_validate.py first")
    df = pd.read_parquet(c.FLAGGED_PATH)
    checks = c.read_json(c.DAY_CHECKS_PATH)["file"]
    holidays, weather = load_holidays(), load_weather()

    dd = build_dim_date(df, holidays, weather)
    fact = pd.DataFrame({
        "appointment_id": df["AppointmentID"], "patient_id": df["PatientId"], "neighbourhood": df["Neighbourhood"],
        "booked_ts": df["booked_ts"].dt.strftime("%Y-%m-%d %H:%M:%S"),
        "appointment_date": df["appointment_date"].dt.strftime("%Y-%m-%d"),
        "lead_days": df["lead_days"], "lead_band": df["lead_band"],
        "sms_eligible": (df["sms_eligible"].astype(bool) & ~df["W03"]).astype(int),
        "sms_received": df["SMS_received"], "no_show": df["no_show"],
        "age": df["Age"], "gender": df["Gender"], "scholarship": df["Scholarship"], "status": df["status"],
    })
    patients = (df.groupby("PatientId").size().rename("appointments").reset_index()
                .rename(columns={"PatientId": "patient_id"}))
    patients["id_ok"] = patients["patient_id"].str.fullmatch(r"\d+").astype(int)
    hoods = df.groupby("Neighbourhood").size().rename("appointments").reset_index() \
        .rename(columns={"Neighbourhood": "neighbourhood"})
    long = df[["AppointmentID"] + rules.RULE_IDS].melt(id_vars="AppointmentID", var_name="rule_id", value_name="hit")
    flags = long[long["hit"]].drop(columns="hit").rename(columns={"AppointmentID": "appointment_id"})

    # between-stage checks
    n_valid, n_excl = int((df["status"] == "valid").sum()), int((df["status"] == "excluded").sum())
    checks.append({"check": "raw_equals_valid_plus_excluded", "status": "PASS" if n_valid + n_excl == len(df) else "FAIL",
                   "detail": f"{len(df)} = {n_valid} + {n_excl}"})
    joined = fact["appointment_date"].isin(dd["date"]).all() and fact["patient_id"].isin(patients["patient_id"]).all()
    checks.append({"check": "every_appointment_joins_date_and_patient", "status": "PASS" if joined else "FAIL",
                   "detail": "100% joined" if joined else "some rows did not join"})

    day_checks = []
    if holidays is None:
        day_checks.append({"check": "weekdays_without_appointments_explained", "status": "WARN",
                           "detail": "holiday API not available, check not run"})
    else:
        empty = dd[(dd["is_weekday"] == 1) & (dd["appointments"] == 0)]
        unexplained = empty[empty["holiday_name"].isna()]["date"].tolist()
        explained = [f"{r.date} {r.holiday_name}" for r in empty[empty["holiday_name"].notna()].itertuples()]
        day_checks.append({"check": "weekdays_without_appointments_explained", "status": "WARN" if unexplained else "PASS",
                           "detail": f"holidays: {explained}; not explained: {unexplained}"})
    outages = dd[dd["reminder_outage"] == 1]["date"].tolist()
    day_checks.append({"check": "reminder_coverage_above_outage_level", "status": "WARN" if outages else "PASS",
                       "detail": f"{len(outages)} appointment days under {c.OUTAGE_COVERAGE_BELOW:.0f}%: {outages}"})
    open_days = dd[dd["appointments"] > 0]
    if weather is None:
        day_checks.append({"check": "weather_covers_every_appointment_day", "status": "WARN", "detail": "weather API not available"})
    else:
        miss = open_days[open_days["precipitation_mm"].isna()]["date"].tolist()
        day_checks.append({"check": "weather_covers_every_appointment_day", "status": "WARN" if miss else "PASS",
                           "detail": f"missing: {miss}" if miss else f"{len(open_days)} of {len(open_days)} days"})
    for ch in day_checks:
        (log.warning if ch["status"] == "WARN" else log.info)(f"check {ch['check']}: {ch['status']} ({ch['detail']})")

    all_checks = pd.DataFrame([dict(scope="file", **ch) for ch in checks] + [dict(scope="day", **ch) for ch in day_checks])

    # build in a .part file and swap it in only when complete
    c.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    part = c.DB_PATH.with_suffix(".db.part")
    part.unlink(missing_ok=True)
    con = sqlite3.connect(part)
    con.executescript(SCHEMA)
    for name, frame in [("dim_patient", patients[["patient_id", "id_ok", "appointments"]]),
                        ("dim_neighbourhood", hoods), ("dim_date", dd), ("fact_appointment", fact),
                        ("appointment_flag", flags), ("validation_rule", rules.rules_table()),
                        ("run_check", all_checks)]:
        frame.to_sql(name, con, if_exists="append", index=False)
    con.commit()
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ["fact_appointment", "dim_patient", "dim_date", "appointment_flag", "appointment_event"]}
    con.close()
    part.replace(c.DB_PATH)
    all_checks.to_csv(c.OUTPUT_DIR / "run_checks.csv", index=False)

    n_pass = int((all_checks["status"] == "PASS").sum())
    log.info(f"model done: {json.dumps(counts)}; checks {n_pass}/{len(all_checks)} PASS")
    return 0


if __name__ == "__main__":
    c.run_stage(main, "stage3_model")
