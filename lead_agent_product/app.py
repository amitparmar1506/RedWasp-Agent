import os
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List

from flask import Flask, jsonify, render_template, request, send_file


PRODUCT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PRODUCT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from marketing.lead_enrichment_agent import (  # noqa: E402
    DEFAULT_INPUT,
    DEFAULT_OUTPUT,
    enrich_rows,
    load_env_file,
    read_rows,
    write_rows,
)


ENV_PATH = PROJECT_ROOT / ".env"
RUN_DIR = PRODUCT_DIR / "runs"
RUN_DIR.mkdir(exist_ok=True)
load_env_file(ENV_PATH)

app = Flask(__name__, template_folder="templates", static_folder="static")

JOBS: Dict[str, Dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()


def authorized() -> bool:
    expected = os.getenv("LEAD_AGENT_TOKEN", "").strip()
    supplied = (request.headers.get("X-Agent-Token") or request.args.get("token") or "").strip()
    return bool(expected and supplied and expected == supplied)


def safe_status(job_id: str, **updates: Any) -> None:
    with JOBS_LOCK:
        job = JOBS.setdefault(job_id, {})
        job.update(updates)


def run_enrichment_job(job_id: str, input_path: Path, output_path: Path, limit: int, delay: float) -> None:
    try:
        safe_status(job_id, status="running", message="Reading CSV...")
        rows = read_rows(input_path)
        if not rows:
            safe_status(job_id, status="failed", message="CSV has no rows.")
            return

        safe_status(job_id, message=f"Enriching {min(limit, len(rows))} restaurants...")
        enriched = enrich_rows(rows, min(limit, len(rows)), delay)

        base_fields: List[str] = list(rows[0].keys())
        extra_fields = [
            "google_maps_url",
            "address",
            "rating",
            "review_count",
            "business_status",
            "match_name",
            "match_confidence",
            "website_pages_checked",
        ]
        fieldnames = base_fields + [field for field in extra_fields if field not in base_fields]
        write_rows(output_path, enriched, fieldnames)
        safe_status(
            job_id,
            status="completed",
            message=f"Enriched {len(enriched)} leads.",
            download_url=f"/download/{job_id}",
        )
    except Exception as exc:  # pragma: no cover - surfaced to the operator UI
        safe_status(job_id, status="failed", message=str(exc))


@app.get("/")
def index() -> str:
    enabled = bool(os.getenv("GOOGLE_MAPS_API_KEY", "").strip())
    protected = bool(os.getenv("LEAD_AGENT_TOKEN", "").strip())
    return render_template("index.html", maps_enabled=enabled, protected=protected)


@app.post("/jobs")
def create_job() -> Any:
    if os.getenv("LEAD_AGENT_TOKEN", "").strip() and not authorized():
        return jsonify({"error": "Unauthorized"}), 401

    limit = max(1, min(500, int(request.form.get("limit", "25"))))
    delay = max(0.5, min(10.0, float(request.form.get("delay", "1.2"))))
    uploaded = request.files.get("csv_file")

    job_id = uuid.uuid4().hex[:12]
    job_dir = RUN_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    input_path = job_dir / "input.csv"
    output_path = job_dir / "enriched.csv"

    if uploaded and uploaded.filename:
        uploaded.save(input_path)
    else:
        input_path.write_text((PROJECT_ROOT / DEFAULT_INPUT).read_text(encoding="utf-8"), encoding="utf-8")

    safe_status(job_id, status="queued", message="Queued.", download_url="")
    worker = threading.Thread(
        target=run_enrichment_job,
        args=(job_id, input_path, output_path, limit, delay),
        daemon=True,
    )
    worker.start()
    return jsonify({"job_id": job_id})


@app.get("/jobs/<job_id>")
def get_job(job_id: str) -> Any:
    if os.getenv("LEAD_AGENT_TOKEN", "").strip() and not authorized():
        return jsonify({"error": "Unauthorized"}), 401

    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify({"error": "Job not found."}), 404
        return jsonify(job)


@app.get("/download/<job_id>")
def download(job_id: str) -> Any:
    if os.getenv("LEAD_AGENT_TOKEN", "").strip() and not authorized():
        return jsonify({"error": "Unauthorized"}), 401

    path = RUN_DIR / job_id / "enriched.csv"
    if not path.exists():
        return jsonify({"error": "File is not ready."}), 404
    return send_file(path, as_attachment=True, download_name="restaurant_leads_enriched.csv")


def get_port() -> int:
    raw_port = os.getenv("LEAD_AGENT_PORT", "5150")
    return int(raw_port) if raw_port.isdigit() else 5150


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=get_port(), debug=False)
