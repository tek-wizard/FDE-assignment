"""Run the whole pipeline: ingest -> validate -> model -> metrics.

    python run_pipeline.py

Each stage is its own script so it can also be run alone. If a stage exits with an
error the later stages are not run, so the metric outputs are only rewritten when every
earlier stage worked. Exit code 2 from the metrics stage means the run was held.
"""
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "scripts"))
import common as c  # noqa: E402

STAGES = ["stage1_retrieve.py", "stage2_validate.py", "stage3_model.py", "stage4_metrics.py"]


def main():
    args = c.parse_args("Run the full clinic no-show pipeline")
    log = c.get_logger("run_pipeline")
    passthrough = ["--max-fail-share", str(args.max_fail_share)]
    if args.refresh_api:
        passthrough.append("--refresh-api")
    log.info("===== pipeline run start =====")
    started = time.time()
    for stage in STAGES:
        t0 = time.time()
        code = subprocess.call([sys.executable, str(c.ROOT / "scripts" / stage)] + passthrough)
        log.info(f"{stage} finished with exit code {code} in {time.time() - t0:.1f}s")
        if code == 2 and stage == STAGES[-1]:
            log.error("pipeline finished but the run was HELD, see outputs/run_checks.csv")
            sys.exit(2)
        if code != 0:
            log.error(f"pipeline stopped at {stage}; later stages not run")
            sys.exit(1)
    log.info(f"===== pipeline run OK in {time.time() - started:.1f}s =====")


if __name__ == "__main__":
    main()
