"""Validation rules and small derivation helpers.

FAIL = the row can't be trusted as an appointment, so it is excluded from all metrics.
WARN = the appointment still counts, but a field is suspect, so it is left out of the metric that uses that field.
INFO = recorded and counted only, no row is excluded.
Nothing is deleted: every raw row stays in fact_appointment with its flags.
"""
import pandas as pd

from common import SMS_MIN_LEAD_DAYS, lead_band

BINARY_FLAGS = ["Scholarship", "Hipertension", "Diabetes", "Alcoholism", "SMS_received"]

RULES = [
    ("F01", "appointment_before_booking", "FAIL",
     "appointment date is earlier than the booking date",
     "a slot can't be booked after it happened; lead time and reminder eligibility are both wrong",
     "excluded from all metrics"),
    ("F02", "age_negative", "FAIL",
     "Age < 0",
     "not a real patient record, probably a test or typo row",
     "excluded from all metrics"),
    ("F03", "duplicate_appointment_id", "FAIL",
     "AppointmentID appears more than once",
     "one slot would be counted twice in the no-show rate",
     "excluded from all metrics (every copy)"),
    ("F04", "outcome_not_yes_no", "FAIL",
     "No-show is not 'Yes' or 'No'",
     "the outcome is the KPI; without it the row can't be counted",
     "excluded from all metrics"),
    ("F05", "flag_not_0_1", "FAIL",
     "Scholarship, Hipertension, Diabetes, Alcoholism or SMS_received not 0/1",
     "SMS_received is the intervention; a bad value would put the row in the wrong group",
     "excluded from all metrics"),
    ("W01", "age_over_100", "WARN",
     "Age > 100",
     "possible but rare (max is 115); likely a typo for some",
     "kept, left out of age breakdowns"),
    ("W02", "patient_id_not_integer", "WARN",
     "PatientId has a decimal part",
     "the ID looks corrupted, so the patient's history can't be linked",
     "kept, left out of the repeat no-show metric"),
    ("W03", "sms_below_min_lead", "WARN",
     f"SMS_received = 1 but booked less than {SMS_MIN_LEAD_DAYS} days ahead",
     "goes against the sending pattern seen in the data; would blur the eligible group",
     "kept, not counted as reminder-eligible"),
    ("I01", "handcap_over_1", "INFO",
     "Handcap is 2, 3 or 4",
     "the Kaggle description says True/False, but it looks like a count of disabilities",
     "no action, not used by any metric"),
    ("I02", "weekend_appointment", "INFO",
     "appointment on a Saturday or Sunday",
     "only one Saturday has appointments; could be a campaign day",
     "no action"),
    ("I03", "same_patient_same_day", "INFO",
     "patient has more than one appointment on that day",
     "several slots in one visit; they usually share the outcome",
     "counted per slot, noted as a limitation"),
    ("I04", "age_zero", "INFO",
     "Age = 0",
     "babies under 1 year, a real group (paediatric visits)",
     "no action"),
]
RULE_IDS = [r[0] for r in RULES]
FAIL_IDS = [r[0] for r in RULES if r[2] == "FAIL"]


def rules_table():
    return pd.DataFrame(RULES, columns=["rule_id", "rule", "severity", "check", "business_reason", "action"])


def add_derived(df):
    """Parse dates and add lead time, reminder eligibility and the outcome as a boolean.

    ScheduledDay is marked 'Z' (UTC) but the booking hours run 06:00-21:00 with a peak at 07:00,
    which fits local clinic hours, so the timestamps are treated as local time and not converted.
    AppointmentDay has no time of day (always 00:00), so lead time is in calendar days.
    """
    df = df.copy()
    df["booked_ts"] = pd.to_datetime(df["ScheduledDay"]).dt.tz_localize(None)
    df["appointment_date"] = pd.to_datetime(df["AppointmentDay"]).dt.tz_localize(None).dt.normalize()
    df["lead_days"] = (df["appointment_date"] - df["booked_ts"].dt.normalize()).dt.days
    df["lead_band"] = df["lead_days"].map(lead_band)
    df["no_show"] = df["No-show"].map({"Yes": 1, "No": 0})
    df["sms_eligible"] = (df["lead_days"] >= SMS_MIN_LEAD_DAYS).astype(int)
    df["weekday"] = df["appointment_date"].dt.day_name()
    return df


def flag_rows(df):
    """Return a DataFrame of booleans, one column per rule id. df must have add_derived() columns."""
    f = pd.DataFrame(index=df.index)
    f["F01"] = df["lead_days"] < 0
    f["F02"] = df["Age"] < 0
    f["F03"] = df["AppointmentID"].duplicated(keep=False)
    f["F04"] = df["no_show"].isna()
    f["F05"] = ~df[BINARY_FLAGS].isin([0, 1]).all(axis=1)
    f["W01"] = df["Age"] > 100
    f["W02"] = ~df["PatientId"].str.fullmatch(r"\d+")
    f["W03"] = (df["SMS_received"] == 1) & (df["lead_days"] < SMS_MIN_LEAD_DAYS)
    f["I01"] = df["Handcap"] > 1
    f["I02"] = df["appointment_date"].dt.dayofweek >= 5
    f["I03"] = df.duplicated(["PatientId", "appointment_date"], keep=False)
    f["I04"] = df["Age"] == 0
    return f.fillna(False).astype(bool)


def row_status(flags):
    return flags[FAIL_IDS].any(axis=1).map({True: "excluded", False: "valid"})
