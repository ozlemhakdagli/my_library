import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    port: int
    db_path: str
    default_lang: str
    backup_dir: str = "/data/backups"
    cover_dir: str = "/data/covers"
    llm_url: str = "http://host.docker.internal:1234/v1"
    llm_model: str = ""
    llm_timeout: float = 60.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            port=int(os.environ.get("LIBRARY_PORT", "8765")),
            db_path=os.environ.get("LIBRARY_DB", "/data/library.db"),
            default_lang=os.environ.get("LIBRARY_DEFAULT_LANG", "en"),
            backup_dir=os.environ.get("LIBRARY_BACKUP_DIR", "/data/backups"),
            cover_dir=os.environ.get("LIBRARY_COVER_DIR", "/data/covers"),
            llm_url=os.environ.get("LIBRARY_LLM_URL", "http://host.docker.internal:1234/v1"),
            llm_model=os.environ.get("LIBRARY_LLM_MODEL", ""),
            llm_timeout=float(os.environ.get("LIBRARY_LLM_TIMEOUT", "60")),
        )
