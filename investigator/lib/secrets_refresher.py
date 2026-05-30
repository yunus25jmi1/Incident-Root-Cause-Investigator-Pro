import os
import time
from pathlib import Path
from dotenv import load_dotenv


class SecretsRefresher:
    def __init__(self, dotenv_path: str | None = None):
        self._dotenv_path = dotenv_path or self._find_dotenv()
        self._known_mtime: float = 0.0

    @staticmethod
    def _find_dotenv() -> str:
        candidates = [".env", ".env.local", os.environ.get("DOTENV_PATH", "")]
        for c in candidates:
            if c and Path(c).exists():
                return c
        return ".env"

    async def refresh_if_changed(self) -> bool:
        try:
            mtime = os.path.getmtime(self._dotenv_path)
        except OSError:
            return False
        if mtime > self._known_mtime:
            load_dotenv(dotenv_path=self._dotenv_path, override=True)
            self._known_mtime = mtime
            return True
        return False
