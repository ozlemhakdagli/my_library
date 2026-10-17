import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    port: int
    db_path: str
    default_lang: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            port=int(os.environ.get("LIBRARY_PORT", "8765")),
            db_path=os.environ.get("LIBRARY_DB", "/data/library.db"),
            default_lang=os.environ.get("LIBRARY_DEFAULT_LANG", "en"),
        )
