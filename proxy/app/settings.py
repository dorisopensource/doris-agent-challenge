import os
from dataclasses import dataclass
from pathlib import Path

PROXY_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    agent_url: str = "http://agent:8000"
    image_base_url: str = "https://raw.githubusercontent.com/dorisopensource/doris-agent-challenge/main/seed-images"
    seed_dir: Path = PROXY_DIR / "seed"
    images_dir: Path = PROXY_DIR.parent / "seed-images"
    faults_file: Path | None = None  # no injected failures unless FAULTS_FILE points to a rules file
    catalog_overrides_file: Path | None = None
    db_path: str = "/data/proxy.db"
    turn_timeout_s: float = 100.0
    latency_scale: float = 1.0

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ.get
        d = cls()
        path = lambda name, default: Path(env(name)) if env(name) else default
        return cls(
            agent_url=env("AGENT_URL", d.agent_url),
            image_base_url=env("IMAGE_BASE_URL", d.image_base_url),
            seed_dir=path("SEED_DIR", d.seed_dir),
            images_dir=path("IMAGES_DIR", d.images_dir),
            faults_file=path("FAULTS_FILE", d.faults_file),
            catalog_overrides_file=path("CATALOG_OVERRIDES_FILE", d.catalog_overrides_file),
            db_path=env("DB_PATH", d.db_path),
            turn_timeout_s=float(env("TURN_TIMEOUT_S", d.turn_timeout_s)),
            latency_scale=float(env("LATENCY_SCALE", d.latency_scale)),
        )
