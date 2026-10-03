import os
from pathlib import Path
from dotenv import load_dotenv
from huggingface_hub import snapshot_download

PROJECT_DIR = Path(__file__).resolve().parent
load_dotenv(PROJECT_DIR.parent / ".env")   # тот же .env

# На время загрузки — принудительно онлайн
os.environ["HF_HUB_OFFLINE"] = "0"

token = os.getenv("HF_TOKEN")
if not token:
    raise SystemExit("HF_TOKEN не задан в .env")

REPOS = [
    "pyannote/speaker-diarization-3.1",
    "pyannote/segmentation-3.0",
    "pyannote/wespeaker-voxceleb-resnet34-LM",
    "pyannote/speaker-diarization-community-1",
    "sentence-transformers/all-MiniLM-L6-v2",
]

for repo in REPOS:
    print("downloading:", repo)
    snapshot_download(repo_id=repo, token=token)
    print("ok:", repo)

print("\nHF cache:", os.getenv("HF_HOME") or "(default)")