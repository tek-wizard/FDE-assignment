"""Shared paths, settings and helpers for the pipeline stages."""
import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
API_DIR = RAW_DIR / "api"
PROCESSED_DIR = ROOT / "data" / "processed"
OUTPUT_DIR = ROOT / "outputs"
LOG_DIR = ROOT / "logs"

MANIFEST_PATH = RAW_DIR / "manifest.json"
APPTS_CSV = RAW_DIR / "appointments_may2016.csv"
HOLIDAYS_JSON = API_DIR / "holidays_BR_2016.json"
WEATHER_JSON = API_DIR / "weather_vitoria.json"
FLAGGED_PATH = PROCESSED_DIR / "flagged_appointments.parquet"
DAY_CHECKS_PATH = PROCESSED_DIR / "day_checks.json"
DB_PATH = PROCESSED_DIR / "clinic.db"

# The dataset is "Medical Appointment No Shows" (Kaggle, joniarroba/noshowappointments, CC BY-NC-SA 4.0).
# Kaggle needs a login, so the pipeline pulls public GitHub copies of the same file and only accepts a copy
# whose sha256 matches the one below. I checked that three independent copies are byte-identical.
APPTS_URLS = [
    "https://raw.githubusercontent.com/alteryx/predict-appointment-noshow/master/data/KaggleV2-May-2016.csv",
    "https://raw.githubusercontent.com/daniel-codes/medical-no-shows/master/noshowappointments-kagglev2-may-2016.csv",
    "https://raw.githubusercontent.com/xShaimaa/Data-Analysis-Projects/main/03-Medical-Appointment-No-Show/"
    "noshowappointments-kagglev2-may-2016.csv",
]
APPTS_SHA256 = "9132d3e7d0246617df9041d3764f20ad6f08e7b0d9f0997fa254fc5e52eda27d"
APPTS_ROWS = 110527

HOLIDAYS_URL = "https://date.nager.at/api/v3/PublicHolidays/2016/BR"
# Open-Meteo historical weather for Vitoria, Espirito Santo (the clinics are in Vitoria's neighbourhoods)
WEATHER_URL = "https://archive-api.open-meteo.com/v1/archive"
WEATHER_PARAMS = {
    "latitude": -20.32, "longitude": -40.34,
    "daily": "precipitation_sum,temperature_2m_max",
    "timezone": "America/Sao_Paulo",
}

REQUIRED_COLUMNS = [
    "PatientId", "AppointmentID", "Gender", "ScheduledDay", "AppointmentDay", "Age", "Neighbourhood",
    "Scholarship", "Hipertension", "Diabetes", "Alcoholism", "Handcap", "SMS_received", "No-show",
]

# SMS reminders are never sent when the appointment is booked less than this many days ahead
# (0 SMS in 50,501 such rows). I use it to define who was eligible for a reminder.
SMS_MIN_LEAD_DAYS = 3
LEAD_BANDS = [(0, 0, "0 same day"), (1, 2, "1-2 days"), (3, 7, "3-7 days"),
              (8, 14, "8-14 days"), (15, 30, "15-30 days"), (31, 9999, "31+ days")]

# Decision triggers and gates (reasons in docs/metric_definitions.md)
OUTAGE_COVERAGE_BELOW = 50.0     # an appointment day where under 50% of eligible appointments got an SMS
TRIGGER_KPI_ABOVE = 30.0         # weekly advance-booked no-show rate above 30%: review that week
TRIGGER_COVERAGE_BELOW = 70.0    # weekly reminder coverage below 70%: ask the SMS vendor what failed
MAX_FAIL_SHARE = 0.02            # hold the run if more than 2% of rows fail a FAIL rule


class PipelineError(Exception):
    pass


def parse_args(description):
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--refresh-api", action="store_true", help="re-fetch the two APIs even if cached")
    p.add_argument("--max-fail-share", type=float, default=MAX_FAIL_SHARE,
                   help="hold the run if more than this share of rows hit a FAIL rule (default 0.02)")
    return p.parse_args()


def get_logger(stage):
    """Log to the console and to logs/pipeline.log. The logger name is the stage name."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            handlers=[logging.FileHandler(LOG_DIR / "pipeline.log"), logging.StreamHandler(sys.stdout)],
        )
    logging.getLogger("matplotlib").setLevel(logging.WARNING)
    return logging.getLogger(stage)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text())


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n")
    tmp.replace(path)


def lead_band(days):
    for lo, hi, name in LEAD_BANDS:
        if lo <= days <= hi:
            return name
    return "invalid"


def run_stage(main, stage):
    """Run a stage's main() and turn errors into a logged message and exit code 1."""
    log = get_logger(stage)
    try:
        code = main(log)
    except PipelineError as e:
        log.error(str(e))
        sys.exit(1)
    sys.exit(code or 0)
