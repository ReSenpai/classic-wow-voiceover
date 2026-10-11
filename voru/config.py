from dataclasses import dataclass, fields
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CLIENT_PROFILE_PATH = REPO_ROOT / "config" / "client.yaml"


@dataclass(frozen=True)
class ClientProfile:
    flavor: str
    version: str
    build: int
    interface: int
    locale: str


def load_client_profile(path=CLIENT_PROFILE_PATH):
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    missing = [f.name for f in fields(ClientProfile) if f.name not in data]
    if missing:
        raise ValueError(f"{path}: missing fields: {', '.join(missing)}")
    return ClientProfile(**{f.name: f.type(data[f.name]) for f in fields(ClientProfile)})
