"""Stage 4: compute the metrics in SQL and write the evidence outputs.

The run is HELD (no metric values published) if any file-level check FAILED.
Day-level WARNs (reminder outage days, weekdays with no appointments) are published with the metrics.
Each week is checked against the decision triggers in common.py.
"""
import sqlite3

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

import common as c

BAND_ORDER = [b[2] for b in c.LEAD_BANDS]
BLUE, ORANGE, GREY, INK = "#2a78d6", "#eb6834", "#9a9893", "#52514e"

# weeks start on Monday; date(d, 'weekday 0', '-6 days') is the Monday of d's week
WEEKLY_SQL = """
WITH v AS (SELECT * FROM fact_appointment WHERE status = 'valid')
SELECT
    date(v.appointment_date, 'weekday 0', '-6 days')              AS week_start,
    COUNT(*)                                                       AS valid_appointments,
    SUM(lead_days >= 1)                                            AS advance_booked,
    SUM(lead_days >= 1 AND no_show = 1)                            AS advance_no_shows,
    SUM(sms_eligible)                                              AS reminder_eligible,
    SUM(sms_eligible AND sms_received)                             AS reminders_received,
    SUM(lead_days > 14)                                            AS booked_over_14_days,
    SUM(lead_days = 0)                                             AS same_day,
    SUM(lead_days = 0 AND no_show = 1)                             AS same_day_no_shows
FROM v
GROUP BY week_start ORDER BY week_start
"""

WEEK_DAYS_SQL = """
SELECT date(date, 'weekday 0', '-6 days') AS week_start,
       SUM(appointments > 0) AS open_days, SUM(reminder_outage) AS outage_days
FROM dim_date GROUP BY week_start
"""

# the confound: reminders are only sent 3+ days ahead, and no-shows rise with lead time
BAND_SQL = """
SELECT lead_band, sms_eligible, sms_received,
       COUNT(*) AS appointments, SUM(no_show) AS no_shows
FROM fact_appointment WHERE status = 'valid'
GROUP BY lead_band, sms_eligible, sms_received
"""

# eligible appointments on reminder-outage days vs normal days (nobody chose to be in an outage)
OUTAGE_SQL = """
SELECT f.lead_band, d.reminder_outage, COUNT(*) AS appointments, SUM(f.no_show) AS no_shows
FROM fact_appointment f JOIN dim_date d ON d.date = f.appointment_date
WHERE f.status = 'valid' AND f.sms_eligible = 1 AND d.is_weekday = 1
GROUP BY f.lead_band, d.reminder_outage
"""

# prior no-shows of the same patient on earlier days (same-day slots don't count as history)
REPEAT_SQL = """
WITH v AS (
    SELECT f.patient_id, f.appointment_date, f.no_show, f.lead_days
    FROM fact_appointment f JOIN dim_patient p USING (patient_id)
    WHERE f.status = 'valid' AND p.id_ok = 1
), h AS (
    SELECT *,
        SUM(no_show) OVER w AS prior_no_shows,
        COUNT(*)     OVER w AS prior_appointments
    FROM v
    WINDOW w AS (PARTITION BY patient_id ORDER BY julianday(appointment_date)
                 RANGE BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
)
SELECT CASE WHEN COALESCE(prior_no_shows, 0) = 0 THEN '0' WHEN prior_no_shows = 1 THEN '1' ELSE '2+' END AS prior,
       COUNT(*) AS appointments, SUM(no_show) AS no_shows
FROM h WHERE COALESCE(prior_appointments, 0) > 0 AND lead_days >= 1
GROUP BY prior ORDER BY prior
"""

# the operational output: who reception should phone (patients with 2+ earlier no-shows), per week
CALL_LIST_SQL = """
WITH v AS (
    SELECT f.appointment_id, f.patient_id, f.appointment_date, f.neighbourhood, f.no_show, f.lead_days
    FROM fact_appointment f JOIN dim_patient p USING (patient_id)
    WHERE f.status = 'valid' AND p.id_ok = 1
), h AS (
    SELECT *, SUM(no_show) OVER (PARTITION BY patient_id ORDER BY julianday(appointment_date)
                                 RANGE BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prior_no_shows
    FROM v
)
SELECT date(appointment_date, 'weekday 0', '-6 days') AS week_start, appointment_id, patient_id,
       appointment_date, neighbourhood, prior_no_shows, no_show
FROM h WHERE prior_no_shows >= 2 AND lead_days >= 1
ORDER BY appointment_date, neighbourhood
"""

CONCENTRATION_SQL = """
WITH k AS (
    SELECT f.patient_id, SUM(f.no_show) AS no_shows
    FROM fact_appointment f JOIN dim_patient p USING (patient_id)
    WHERE f.status = 'valid' AND p.id_ok = 1
    GROUP BY f.patient_id
)
SELECT COUNT(*) AS patients,
       SUM(no_shows >= 2) AS repeat_patients,
       SUM(no_shows) AS no_shows,
       SUM(CASE WHEN no_shows >= 2 THEN no_shows ELSE 0 END) AS repeat_no_shows
FROM k
"""

DAILY_SQL = """
SELECT d.date, d.weekday, d.holiday_name, d.appointments, d.eligible_valid, d.sms_valid,
       d.reminder_coverage, d.reminder_outage, d.precipitation_mm,
       ROUND(100.0 * AVG(f.no_show), 2) AS no_show_pct
FROM dim_date d LEFT JOIN fact_appointment f ON f.appointment_date = d.date AND f.status = 'valid'
GROUP BY d.date ORDER BY d.date
"""


def pct(a, b):
    return round(100 * a / b, 2) if b else None


def standardised_gap(frame, group_col, treated, control, labels=("with_sms", "without_sms")):
    """No-show gap control - treated inside each lead band, weighted by the band's size. In points."""
    rows, total = [], 0
    for band in BAND_ORDER:
        b = frame[frame["lead_band"] == band]
        t, u = b[b[group_col] == treated], b[b[group_col] == control]
        if t["appointments"].sum() == 0 or u["appointments"].sum() == 0:
            continue
        rt = t["no_shows"].sum() / t["appointments"].sum()
        ru = u["no_shows"].sum() / u["appointments"].sum()
        n = b["appointments"].sum()
        rows.append({"lead_band": band, "appointments": int(n),
                     f"no_show_pct_{labels[0]}": round(100 * rt, 2), f"no_show_pct_{labels[1]}": round(100 * ru, 2),
                     "gap_points": round(100 * (ru - rt), 2)})
        total += n
    gap = sum(r["gap_points"] * r["appointments"] for r in rows) / total if total else None
    return round(gap, 2) if gap is not None else None, pd.DataFrame(rows)


def dashboard(weekly, daily, band_effect, repeat, path):
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.edgecolor": GREY, "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK})
    fig, ax = plt.subplots(2, 2, figsize=(12, 7.2))

    a = ax[0, 0]
    wk = weekly.dropna(subset=["kpi_no_show_pct"])
    a.plot(wk["week_start"], wk["kpi_no_show_pct"], color=BLUE, lw=2, marker="o", ms=5)
    a.axhline(c.TRIGGER_KPI_ABOVE, color=GREY, ls="--", lw=1)
    a.text(0, c.TRIGGER_KPI_ABOVE + 0.2, "trigger", color=GREY)
    a.set_ylim(20, 35)
    a.set_title("1. KPI: no-show rate, appointments booked 1+ days ahead (%)", loc="left")
    a.tick_params(axis="x", rotation=30)

    a = ax[0, 1]
    d = daily[daily["eligible_valid"] >= 50]
    labels = d["date"].str[5:].tolist()
    a.bar(labels, d["reminder_coverage"], color=BLUE, width=0.8)
    for i, o in enumerate(d["reminder_outage"]):
        if o:
            a.axvspan(i - 0.45, i + 0.45, color=ORANGE, alpha=0.18, lw=0)
            a.text(i, 3, "0%", ha="center", color=INK, fontsize=7)
    a.axhline(c.OUTAGE_COVERAGE_BELOW, color=GREY, ls="--", lw=1)
    a.set_ylim(0, 100)
    a.set_title("2. SMS coverage per day (% of eligible); dashed = 50% outage level", loc="left")
    a.tick_params(axis="x", rotation=90, labelsize=7)

    a = ax[1, 0]
    x = range(len(band_effect))
    a.bar([i - 0.2 for i in x], band_effect["no_show_pct_without_sms"], width=0.38, color=ORANGE, label="no SMS")
    a.bar([i + 0.2 for i in x], band_effect["no_show_pct_with_sms"], width=0.38, color=BLUE, label="SMS received")
    a.set_xticks(list(x), band_effect["lead_band"])
    a.set_title("3. No-show % by lead time: with vs without SMS (eligible only)", loc="left")
    a.legend(frameon=False)

    a = ax[1, 1]
    a.bar(repeat["prior"], repeat["no_show_pct"], color=BLUE, width=0.55)
    for i, v in enumerate(repeat["no_show_pct"]):
        a.text(i, v + 0.6, f"{v:.1f}%", ha="center", color=INK)
    a.set_xlabel("earlier no-shows by the same patient in the window")
    a.set_title("4. No-show % of returning patients' advance bookings", loc="left")

    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main(log):
    c.parse_args("Stage 4: metrics")
    if not c.DB_PATH.exists():
        raise c.PipelineError("no model found, run stage3_model.py first")
    con = sqlite3.connect(c.DB_PATH)
    checks = pd.read_sql("SELECT * FROM run_check", con)
    failed = checks[(checks["scope"] == "file") & (checks["status"] == "FAIL")]
    held = len(failed) > 0

    weekly = pd.read_sql(WEEKLY_SQL, con).merge(pd.read_sql(WEEK_DAYS_SQL, con), on="week_start", how="left")
    weekly["kpi_no_show_pct"] = [pct(a, b) for a, b in zip(weekly["advance_no_shows"], weekly["advance_booked"])]
    weekly["reminder_coverage_pct"] = [pct(a, b) for a, b in zip(weekly["reminders_received"], weekly["reminder_eligible"])]
    weekly["booked_over_14_days_pct"] = [pct(a, b) for a, b in zip(weekly["booked_over_14_days"], weekly["advance_booked"])]
    weekly["same_day_no_show_pct"] = [pct(a, b) for a, b in zip(weekly["same_day_no_shows"], weekly["same_day"])]
    triggers = []
    for r in weekly.itertuples():
        fired = []
        if r.kpi_no_show_pct is not None and r.kpi_no_show_pct > c.TRIGGER_KPI_ABOVE:
            fired.append(f"KPI above {c.TRIGGER_KPI_ABOVE:.0f}%")
        if r.reminder_coverage_pct is not None and r.reminder_coverage_pct < c.TRIGGER_COVERAGE_BELOW:
            fired.append(f"reminder coverage below {c.TRIGGER_COVERAGE_BELOW:.0f}%")
        triggers.append("; ".join(fired) or "none")
    weekly["triggers_fired"] = triggers

    bands = pd.read_sql(BAND_SQL, con)
    eligible = bands[bands["sms_eligible"] == 1]
    sms_gap, band_effect = standardised_gap(eligible, "sms_received", 1, 0)
    naive_sms = bands[bands["sms_received"] == 1]
    naive_none = bands[bands["sms_received"] == 0]
    naive_with = pct(naive_sms["no_shows"].sum(), naive_sms["appointments"].sum())
    naive_without = pct(naive_none["no_shows"].sum(), naive_none["appointments"].sum())
    outage_gap, outage_table = standardised_gap(pd.read_sql(OUTAGE_SQL, con), "reminder_outage", 0, 1,
                                                ("normal_days", "outage_days"))

    lead = bands.groupby("lead_band")[["appointments", "no_shows"]].sum().reindex(BAND_ORDER).reset_index()
    lead["no_show_pct"] = (100 * lead["no_shows"] / lead["appointments"]).round(2)

    repeat = pd.read_sql(REPEAT_SQL, con)
    repeat["no_show_pct"] = (100 * repeat["no_shows"] / repeat["appointments"]).round(2)
    conc = pd.read_sql(CONCENTRATION_SQL, con).iloc[0]
    daily = pd.read_sql(DAILY_SQL, con)
    calls = pd.read_sql(CALL_LIST_SQL, con)
    con.close()
    weekly = weekly.merge(calls.groupby("week_start").size().rename("call_list_size"), on="week_start", how="left")
    weekly["call_list_size"] = weekly["call_list_size"].fillna(0).astype(int)

    valid_all = weekly[["advance_booked", "advance_no_shows", "reminder_eligible", "reminders_received",
                        "booked_over_14_days", "same_day", "same_day_no_shows", "valid_appointments"]].sum()
    pooled = {
        "kpi": pct(valid_all["advance_no_shows"], valid_all["advance_booked"]),
        "coverage": pct(valid_all["reminders_received"], valid_all["reminder_eligible"]),
        "coverage_normal_days": pct(daily.loc[daily["reminder_outage"] == 0, "sms_valid"].sum(),
                                    daily.loc[daily["reminder_outage"] == 0, "eligible_valid"].sum()),
        "sms_gap": sms_gap, "outage_gap": outage_gap,
        "naive_with": naive_with, "naive_without": naive_without,
        "repeat_share": pct(conc["repeat_no_shows"], conc["no_shows"]),
        "repeat_patients_pct": pct(conc["repeat_patients"], conc["patients"]),
        "repeat_patients": int(conc["repeat_patients"]),
        "over_14": pct(valid_all["booked_over_14_days"], valid_all["advance_booked"]),
        "same_day": pct(valid_all["same_day_no_shows"], valid_all["same_day"]),
    }
    rain = daily[daily["appointments"] >= 50]
    wet, dry = rain[rain["precipitation_mm"] >= 10], rain[rain["precipitation_mm"] < 1]
    pooled["rain_wet"] = round(wet["no_show_pct"].mean(), 2) if len(wet) else None
    pooled["rain_dry"] = round(dry["no_show_pct"].mean(), 2) if len(dry) else None
    pooled["wet_days"], pooled["dry_days"] = len(wet), len(dry)

    if held:
        for col in ["kpi_no_show_pct", "reminder_coverage_pct", "booked_over_14_days_pct", "same_day_no_show_pct"]:
            weekly[col] = None
        weekly["triggers_fired"] = "HELD"
        log.error(f"run HELD, file checks failed: {failed['check'].tolist()}; metric values left blank")

    out = c.OUTPUT_DIR
    metrics_path = out / "weekly_metrics.csv"
    old = metrics_path.read_text() if metrics_path.exists() else None
    weekly.to_csv(metrics_path, index=False)
    log.info("weekly_metrics.csv is identical to the previous run" if old == metrics_path.read_text()
             else "weekly_metrics.csv changed since the previous run")
    daily.to_csv(out / "daily_reminder_coverage.csv", index=False)
    band_effect.to_csv(out / "reminder_effect_by_lead_band.csv", index=False)
    outage_table.to_csv(out / "outage_vs_normal_days.csv", index=False)
    lead.to_csv(out / "no_show_by_lead_band.csv", index=False)
    repeat.to_csv(out / "no_show_by_prior_no_shows.csv", index=False)

    if held:
        return 2

    # patient-level, so it stays in data/processed (not committed); only the counts go to outputs/
    last_week = weekly["week_start"].max()
    calls[calls["week_start"] == last_week].drop(columns="no_show").to_csv(c.PROCESSED_DIR / "call_list.csv", index=False)
    # the list grows week by week because the window starts with no history, so report the latest week
    lw = weekly[weekly["week_start"] == last_week].iloc[0]
    lw_calls = calls[calls["week_start"] == last_week]
    pooled["call_list_last_week"] = len(lw_calls)
    pooled["call_list_per_day"] = round(len(lw_calls) / lw["open_days"], 0)
    pooled["call_list_per_hood_day"] = round(len(lw_calls) / lw["open_days"] / lw_calls["neighbourhood"].nunique(), 1)
    pooled["call_list_no_show"] = pct(calls["no_show"].sum(), len(calls))
    log.info(f"call list for week {last_week}: {int((calls['week_start'] == last_week).sum())} appointments "
             f"written to data/processed/call_list.csv")

    for r in weekly.itertuples():
        msg = (f"week {r.week_start}: KPI {r.kpi_no_show_pct}%, coverage {r.reminder_coverage_pct}%, "
               f"{r.outage_days} outage day(s)")
        (log.warning if r.triggers_fired != "none" else log.info)(
            msg + ("" if r.triggers_fired == "none" else f" [trigger: {r.triggers_fired}]"))

    dashboard(weekly, daily, band_effect, repeat, out / "dashboard.png")
    write_evidence(weekly, daily, band_effect, outage_table, lead, repeat, pooled, checks, out / "evidence_table.md")
    log.info(f"metrics done: KPI {pooled['kpi']}% pooled, reminder gap {pooled['sms_gap']} pts "
             f"(naive view {pooled['naive_with']}% vs {pooled['naive_without']}%), outputs in outputs/")
    return 0


def write_evidence(weekly, daily, band_effect, outage_table, lead, repeat, p, checks, path):
    outage_days = daily[daily["reminder_outage"] == 1]["date"].tolist()
    day_warn = checks[(checks["scope"] == "day") & (checks["status"] != "PASS")]
    metrics = pd.DataFrame([
        ["KPI", "No-show rate of appointments booked 1+ days ahead", f"{p['kpi']}%",
         f"any week above {c.TRIGGER_KPI_ABOVE:.0f}%: review that week"],
        ["S1", "Reminder coverage: eligible appointments (booked 3+ days ahead) that got an SMS",
         f"{p['coverage']}% ({p['coverage_normal_days']}% on normal days)",
         f"any week below {c.TRIGGER_COVERAGE_BELOW:.0f}%, or a day below {c.OUTAGE_COVERAGE_BELOW:.0f}%: ask the SMS vendor"],
        ["S2", "Reminder effect at the same lead time (no-show points saved by an SMS)",
         f"{p['sms_gap']} pts (outage days vs normal days: {p['outage_gap']} pts)",
         "below 1 pt: the reminder is not worth scaling"],
        ["S3", "Share of no-shows from patients with 2+ no-shows in the window",
         f"{p['repeat_share']}% (from {p['repeat_patients_pct']}% of patients)", "used to size a call list"],
        ["S4", "Advance bookings made more than 14 days ahead", f"{p['over_14']}%", "context for slot policy"],
        ["Ops", "Call list: advance bookings by patients with 2+ earlier no-shows",
         f"{p['call_list_last_week']} in the last week (~{p['call_list_per_day']:.0f} a day, "
         f"~{p['call_list_per_hood_day']} per neighbourhood a day); {p['call_list_no_show']}% of all such bookings no-showed",
         "sent to reception weekly"],
    ], columns=["#", "Metric", "Pooled (6 weeks)", "Decision trigger"])
    week_cols = ["week_start", "open_days", "outage_days", "valid_appointments", "advance_booked",
                 "kpi_no_show_pct", "reminder_coverage_pct", "booked_over_14_days_pct", "call_list_size", "triggers_fired"]
    lines = [
        "# Evidence table: clinic no-shows and SMS reminders",
        "",
        "Built by `python run_pipeline.py` from the Vitoria (Brazil) public clinic appointment extract, "
        "appointment dates 2016-04-29 to 2016-06-08. Pooled = all weeks added up before dividing.",
        "",
        "## Project KPI and supporting metrics",
        "",
        metrics.to_markdown(index=False),
        "",
        "## Why the plain SMS comparison is misleading",
        "",
        f"Read naively, SMS makes things worse: {p['naive_with']}% no-show with an SMS vs {p['naive_without']}% "
        f"without. But nobody booked under {c.SMS_MIN_LEAD_DAYS} days ahead ever gets an SMS, and those bookings "
        f"rarely no-show (same-day: {p['same_day']}%). Compared at the same lead time, SMS appointments no-show less:",
        "",
        band_effect.to_markdown(index=False),
        "",
        f"Check that does not depend on who gets an SMS: on the {len(outage_days)} outage days no eligible appointment "
        f"got a reminder. Same lead time, outage days vs normal days:",
        "",
        outage_table.to_markdown(index=False),
        "",
        "## No-show by lead time (all valid appointments)",
        "",
        lead.to_markdown(index=False),
        "",
        "## Returning patients: no-show % by earlier no-shows",
        "",
        repeat.to_markdown(index=False),
        "",
        "## Weekly values",
        "",
        weekly[week_cols].to_markdown(index=False),
        "",
        "## Context and data gaps",
        "",
        f"- Rain: rainy days (10 mm+, {p['wet_days']} days) averaged {p['rain_wet']}% no-show, "
        f"dry days ({p['dry_days']} days) {p['rain_dry']}%. No sign that rain matters, but {p['wet_days']} rainy days "
        f"is too few to rule it out.",
        "- Partial weeks: the first week has 1 open day (April 29) and the last week 3 (June 6-8).",
        f"- Reminder outage days: {', '.join(outage_days)}.",
    ] + [f"- {r.check}: {r.status} ({r.detail})" for r in day_warn.itertuples()]
    path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    c.run_stage(main, "stage4_metrics")
