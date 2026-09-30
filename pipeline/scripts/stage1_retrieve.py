"""Stage 1: download raw inputs and check the download is complete.

Sources:
  - Appointment extract CSV (HTTPS file download from a public copy, checked against a pinned sha256)
  - Nager.Date public holidays API (JSON), Brazil 2016
  - Open-Meteo historical weather API (JSON), daily rain for Vitoria

Raw files are never edited. data/raw/manifest.json records url, size, sha256 and row counts,
so a rerun can tell if anything changed.
"""
import hashlib
import time
from datetime import datetime, timezone

import pandas as pd
import requests

import common as c

RETRIES = 3
TIMEOUT = 60


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_with_retries(url, log, params=None):
    """GET with 3 attempts and 2 s / 4 s waits. 404 is returned without retrying."""
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT)
            if r.status_code == 404:
                return r
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if attempt == RETRIES:
                raise c.PipelineError(f"{url}: failed after {RETRIES} attempts ({e})")
            wait = 2 ** attempt
            log.warning(f"{url}: attempt {attempt} failed ({e}), retrying in {wait}s")
            time.sleep(wait)


def retrieve_appointments(manifest, log):
    """Use the local copy if it matches the pinned checksum, otherwise try each public copy in turn."""
    if c.APPTS_CSV.exists() and c.sha256_of(c.APPTS_CSV) == c.APPTS_SHA256:
        log.info(f"{c.APPTS_CSV.name}: already present and matches the pinned sha256, skipping download")
        # the manifest may be missing (deleted, or the file was copied in by hand), so rebuild the entry
        return manifest.get("appointments") or {"url": "local copy", "size_bytes": c.APPTS_CSV.stat().st_size,
                                                "sha256": c.APPTS_SHA256, "downloaded_at": None}
    if c.APPTS_CSV.exists():
        log.warning(f"{c.APPTS_CSV.name}: local file does not match the pinned sha256, downloading again")

    for url in c.APPTS_URLS:
        try:
            r = get_with_retries(url, log)
        except c.PipelineError as e:
            log.warning(f"{e}; trying the next copy")
            continue
        if r.status_code == 404:
            log.warning(f"{url}: 404, trying the next copy")
            continue
        got = hashlib.sha256(r.content).hexdigest()
        if got != c.APPTS_SHA256:
            log.warning(f"{url}: sha256 {got[:12]} is not the pinned {c.APPTS_SHA256[:12]}, not using this copy")
            continue
        c.APPTS_CSV.parent.mkdir(parents=True, exist_ok=True)
        part = c.APPTS_CSV.with_suffix(".csv.part")
        part.write_bytes(r.content)
        part.replace(c.APPTS_CSV)
        log.info(f"downloaded {c.APPTS_CSV.name} from {url.split('/')[3]} ({len(r.content):,} bytes, sha256 ok)")
        return {"url": url, "size_bytes": len(r.content), "sha256": got, "downloaded_at": now()}
    raise c.PipelineError("no copy of the appointment CSV matched the pinned sha256. Nothing was replaced.")


def fetch_json(name, url, params, path, old, refresh, log):
    """Fetch an API response and save it exactly as received. Falls back to the cached copy if the API is down."""
    if old and path.exists() and c.sha256_of(path) == old["sha256"] and not refresh:
        log.info(f"API {name}: using cached response ({old['records']} records, use --refresh-api to re-fetch)")
        return old
    try:
        r = get_with_retries(url, log, params)
        if r.status_code == 404:
            raise c.PipelineError(f"{url}: 404")
        body = r.json()
    except (c.PipelineError, ValueError) as e:
        if old and path.exists():
            log.warning(f"API {name}: {e}; using the cached copy from {old['fetched_at']}")
            return old
        raise c.PipelineError(f"{name} API not available and no cached copy ({e})")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.content)
    records = len(body) if isinstance(body, list) else len(body.get("daily", {}).get("time", []))
    log.info(f"API {name}: saved {records} records ({len(r.content):,} bytes)")
    return {"url": r.url, "records": records, "sha256": c.sha256_of(path), "fetched_at": now()}


def main(log):
    args = c.parse_args("Stage 1: retrieve the appointment CSV and the two APIs")
    manifest = c.read_json(c.MANIFEST_PATH, default={})

    manifest["appointments"] = retrieve_appointments(manifest, log)
    df = pd.read_csv(c.APPTS_CSV, usecols=["ScheduledDay", "AppointmentDay"])
    if len(df) != c.APPTS_ROWS:
        raise c.PipelineError(f"appointment CSV has {len(df)} rows, expected {c.APPTS_ROWS}")
    manifest["appointments"]["rows"] = len(df)

    # the weather request covers exactly the appointment dates in the file
    appt = pd.to_datetime(df["AppointmentDay"]).dt.strftime("%Y-%m-%d")
    first, last = appt.min(), appt.max()
    log.info(f"appointment CSV: {len(df):,} rows, appointment dates {first} .. {last}")

    # both APIs only feed day-level checks, so the run carries on without them and stage 3 marks the check WARN
    apis = [("holidays", c.HOLIDAYS_URL, None, c.HOLIDAYS_JSON),
            ("weather", c.WEATHER_URL, dict(c.WEATHER_PARAMS, start_date=first, end_date=last), c.WEATHER_JSON)]
    for name, url, params, path in apis:
        try:
            manifest[name] = fetch_json(name, url, params, path, manifest.get(name), args.refresh_api, log)
        except c.PipelineError as e:
            log.warning(f"API {name}: {e}; continuing without it, its check will be skipped")
            manifest.pop(name, None)
            path.unlink(missing_ok=True)

    c.write_json(c.MANIFEST_PATH, manifest)
    c.OUTPUT_DIR.mkdir(exist_ok=True)
    drop = {"downloaded_at", "fetched_at"}
    c.write_json(c.OUTPUT_DIR / "raw_manifest.json",
                 {k: {kk: vv for kk, vv in v.items() if kk not in drop} for k, v in manifest.items()})
    log.info("retrieve done: 1 CSV file, %d API responses" % sum(k in manifest for k in ["holidays", "weather"]))
    return 0


if __name__ == "__main__":
    c.run_stage(main, "stage1_retrieve")
