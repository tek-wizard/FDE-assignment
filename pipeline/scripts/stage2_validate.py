"""Stage 2: read the raw CSV, run file-level checks, flag every row against the rules.

Output:
  data/processed/flagged_appointments.parquet  every raw row + derived fields + rule flags
  data/processed/day_checks.json               file-level checks used as gates later
  outputs/validation_report.csv                rule counts
"""
import pandas as pd

import common as c
import rules


def check(name, ok, detail, fail_status="FAIL"):
    return {"check": name, "status": "PASS" if ok else fail_status, "detail": detail}


def main(log):
    args = c.parse_args("Stage 2: validate raw appointments")
    manifest = c.read_json(c.MANIFEST_PATH)
    if manifest is None or not c.APPTS_CSV.exists():
        raise c.PipelineError("no raw appointment file found, run stage1_retrieve.py first")

    # remove the old stage 2 output first, so stages 3 and 4 can never use a stale copy
    c.FLAGGED_PATH.unlink(missing_ok=True)
    c.DAY_CHECKS_PATH.unlink(missing_ok=True)

    checks = []
    sha = c.sha256_of(c.APPTS_CSV)
    checks.append(check("raw_checksum_matches_pinned", sha == c.APPTS_SHA256, sha[:12]))
    if sha != c.APPTS_SHA256:
        raise c.PipelineError(f"raw CSV checksum {sha[:12]} is not the pinned one, run stage1_retrieve.py again")

    df = pd.read_csv(c.APPTS_CSV, dtype={"PatientId": str})
    checks.append(check("rows_read_equal_expected", len(df) == c.APPTS_ROWS, f"{len(df)} read vs {c.APPTS_ROWS}"))
    missing = [col for col in c.REQUIRED_COLUMNS if col not in df.columns]
    checks.append(check("required_columns_present", not missing, f"missing: {missing}" if missing else "all present"))
    if missing:
        raise c.PipelineError(f"missing required columns {missing}")
    n_null = int(df[c.REQUIRED_COLUMNS].isna().sum().sum())
    checks.append(check("no_nulls_in_required_columns", n_null == 0, f"{n_null} null cells"))

    df = rules.add_derived(df)
    flags = rules.flag_rows(df)
    df["status"] = rules.row_status(flags)
    df = pd.concat([df, flags], axis=1)

    fail_share = (df["status"] == "excluded").mean()
    checks.append(check("fail_share_below_limit", fail_share <= args.max_fail_share,
                        f"{fail_share:.3%} of rows hit a FAIL rule (limit {args.max_fail_share:.3%})"))

    counts = []
    for rule_id, name, severity, *_rest in rules.RULES:
        n = int(df[rule_id].sum())
        counts.append({"rule_id": rule_id, "rule": name, "severity": severity,
                       "rows_flagged": n, "pct_of_rows": round(100 * n / len(df), 3)})
        if n:
            log.info(f"rule {rule_id} {name} ({severity}): {n:,} rows")
    report = pd.DataFrame(counts).merge(rules.rules_table()[["rule_id", "action"]], on="rule_id")
    c.OUTPUT_DIR.mkdir(exist_ok=True)
    report.to_csv(c.OUTPUT_DIR / "validation_report.csv", index=False)
    rules.rules_table().to_csv(c.OUTPUT_DIR / "validation_rules.csv", index=False)

    for ch in checks:
        if ch["status"] == "FAIL":
            log.error(f"check {ch['check']} FAILED ({ch['detail']}), the run will be held")

    c.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(c.FLAGGED_PATH, index=False)
    c.write_json(c.DAY_CHECKS_PATH, {"file": checks})
    log.info(f"validate done: {len(df):,} rows, {int((df['status'] == 'excluded').sum())} excluded by FAIL rules "
             f"({fail_share:.3%}), report in outputs/validation_report.csv")
    return 0


if __name__ == "__main__":
    c.run_stage(main, "stage2_validate")
