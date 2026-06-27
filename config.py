import os
from pathlib import Path


API_PREFIX = os.getenv("API_PREFIX", "/running_analysis/api")

BACKEND_ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("RUNNING_ANALYSIS_DATA_DIR", BACKEND_ROOT.parent / "data"))
TEMP_UPLOAD_DIR = DATA_DIR / "uploads_temp"
RUN_SESSION_DIR = DATA_DIR / "run_sessions"

PIPELINE_ROOT = Path(
    os.getenv("RUNNER_ANALYSIS_PIPELINE_ROOT", "/home/jeter/runner-analysis-pipeline")
)
PIPELINE_GPU = os.getenv("RUNNER_ANALYSIS_GPU", "0")
ENABLE_MOCK_ON_FAILURE = os.getenv("ENABLE_MOCK_ON_FAILURE", "false").lower() == "true"

TEMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
RUN_SESSION_DIR.mkdir(parents=True, exist_ok=True)
