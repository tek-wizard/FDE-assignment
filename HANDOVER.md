# Handover

This is my FDE assignment: a small data pipeline that looks at missed appointments (no-shows) at public clinics
in Vitoria, Brazil, and checks whether SMS reminders help. The data is real and public. It is not included here;
the first run downloads it.

## What's in the folder

| Path | What it is |
|---|---|
| `problem_brief.pdf` | the problem brief (2 pages) |
| `README.md` | the full write-up: problem, KPI, sources, results, what is still unknown |
| `pipeline/run_pipeline.py` | the pipeline: one command runs all 4 stages |
| `pipeline/scripts/` | the 4 stages (retrieve, validate, model, metrics) plus the rules and settings |
| `pipeline/notebooks/analysis.ipynb` | the working notebook |
| `pipeline/docs/` | stakeholders, workflow, source map, validation rules, metric definitions |
| `pipeline/outputs/` | results from my last run: evidence table, dashboard, checks, run log |
| `pipeline/tests/` | 18 unit tests |

## Run it (about 2 minutes)

You need Python 3.12 and internet for the first run. With `uv`:

```bash
cd pipeline
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
python run_pipeline.py
```

Without `uv`, use `python3.12 -m venv .venv` and `pip install -r requirements.txt` instead.

The first run downloads about 11 MB into `pipeline/data/` and takes about 15 seconds. It should end with:

```
===== pipeline run OK in ...s =====
```

Two WARN lines along the way are expected: they are findings, not errors (7 days with no SMS sent, and 2
weekdays with no appointments).

## Check it worked

```bash
python -m pytest -q tests      # 18 passed
```

Then open `pipeline/outputs/evidence_table.md`. The KPI should be **28.52%** and the reminder effect **5.4 pts**.
If you get the same numbers, you have the same data I had: the pipeline only accepts the file if its checksum
matches.

To rerun the notebook:

```bash
cd notebooks
jupyter nbconvert --to notebook --execute --inplace analysis.ipynb
```

## If something goes wrong

| Problem | Fix |
|---|---|
| `command not found: uv` | use the non-uv commands above, or `pip install uv` |
| `ModuleNotFoundError` | the venv isn't active: `source .venv/bin/activate` |
| download fails | check your internet; the pipeline tries 3 copies of the file. If all fail, download `KaggleV2-May-2016.csv` from https://www.kaggle.com/datasets/joniarroba/noshowappointments, save it as `pipeline/data/raw/appointments_may2016.csv`, and run again |
| exit code 2 | the run was held because too many rows failed validation; see `pipeline/outputs/run_checks.csv` |

## Where to change things

- Thresholds and trigger levels: `pipeline/scripts/common.py`
- Validation rules: `pipeline/scripts/rules.py`
- Metric SQL: `pipeline/scripts/stage4_metrics.py`

## Still open

These need someone at the clinic or the SMS vendor. The data can't answer them:

- Why no SMS went out on May 9, 13 and 16-20.
- Whether "SMS received" means sent or delivered.
- Why May 23 and May 27 have no appointments (May 26 is a holiday; the other two are not).
