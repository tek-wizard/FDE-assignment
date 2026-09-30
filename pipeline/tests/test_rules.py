"""Unit tests for the validation rules and the lead-time logic. No network needed."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import common as c  # noqa: E402
import rules  # noqa: E402
from stage4_metrics import standardised_gap  # noqa: E402


def make(**overrides):
    row = {
        "PatientId": "29872499824296", "AppointmentID": 1, "Gender": "F",
        "ScheduledDay": "2016-05-02T08:00:00Z", "AppointmentDay": "2016-05-10T00:00:00Z",
        "Age": 40, "Neighbourhood": "CENTRO", "Scholarship": 0, "Hipertension": 0, "Diabetes": 0,
        "Alcoholism": 0, "Handcap": 0, "SMS_received": 1, "No-show": "No",
    }
    row.update(overrides)
    return row


def flags_for(*rows):
    df = rules.add_derived(pd.DataFrame(list(rows)))
    return df, rules.flag_rows(df)


def test_clean_row_is_valid():
    df, f = flags_for(make())
    assert not f.loc[0].any()
    assert rules.row_status(f).iloc[0] == "valid"


def test_lead_time_uses_calendar_days():
    df, _ = flags_for(make(ScheduledDay="2016-05-09T23:59:00Z", AppointmentDay="2016-05-10T00:00:00Z"))
    assert df["lead_days"].iloc[0] == 1


def test_same_day_booking_is_lead_zero_and_not_eligible():
    df, _ = flags_for(make(ScheduledDay="2016-05-10T07:00:00Z", SMS_received=0))
    assert df["lead_days"].iloc[0] == 0
    assert df["sms_eligible"].iloc[0] == 0
    assert df["lead_band"].iloc[0] == "0 same day"


def test_appointment_before_booking_fails():
    _, f = flags_for(make(ScheduledDay="2016-05-11T09:00:00Z"))
    assert f.loc[0, "F01"]
    assert rules.row_status(f).iloc[0] == "excluded"


def test_negative_age_fails_but_age_zero_is_info():
    _, f = flags_for(make(Age=-1), make(AppointmentID=2, Age=0))
    assert f.loc[0, "F02"] and rules.row_status(f).iloc[0] == "excluded"
    assert f.loc[1, "I04"] and rules.row_status(f).iloc[1] == "valid"


def test_duplicate_appointment_id_excludes_every_copy():
    _, f = flags_for(make(), make())
    assert f["F03"].all()


def test_bad_outcome_and_bad_sms_flag_fail():
    _, f = flags_for(make(**{"No-show": "Maybe"}), make(AppointmentID=2, SMS_received=2))
    assert f.loc[0, "F04"]
    assert f.loc[1, "F05"]


def test_decimal_patient_id_is_warn_only():
    _, f = flags_for(make(PatientId="93779.52927"))
    assert f.loc[0, "W02"]
    assert rules.row_status(f).iloc[0] == "valid"


def test_sms_before_min_lead_is_warn():
    _, f = flags_for(make(ScheduledDay="2016-05-09T08:00:00Z"))  # 1 day ahead, but SMS_received=1
    assert f.loc[0, "W03"]


def test_handcap_count_is_info_not_fail():
    _, f = flags_for(make(Handcap=3))
    assert f.loc[0, "I01"]
    assert rules.row_status(f).iloc[0] == "valid"


@pytest.mark.parametrize("days,band", [(0, "0 same day"), (2, "1-2 days"), (3, "3-7 days"),
                                       (14, "8-14 days"), (30, "15-30 days"), (179, "31+ days"), (-1, "invalid")])
def test_lead_bands(days, band):
    assert c.lead_band(days) == band


def test_standardised_gap_removes_lead_time_mix():
    # SMS is better by 5 points inside each band, but SMS rows sit mostly in the high-no-show band,
    # so the naive comparison says SMS is worse. The standardised gap must still be +5.
    frame = pd.DataFrame([
        {"lead_band": "3-7 days", "sms_received": 1, "appointments": 100, "no_shows": 15},
        {"lead_band": "3-7 days", "sms_received": 0, "appointments": 900, "no_shows": 180},
        {"lead_band": "31+ days", "sms_received": 1, "appointments": 900, "no_shows": 315},
        {"lead_band": "31+ days", "sms_received": 0, "appointments": 100, "no_shows": 40},
    ])
    naive_with = (15 + 315) / 1000
    naive_without = (180 + 40) / 1000
    assert naive_with > naive_without
    gap, table = standardised_gap(frame, "sms_received", 1, 0)
    assert gap == pytest.approx(5.0)
    assert list(table["gap_points"]) == [5.0, 5.0]
