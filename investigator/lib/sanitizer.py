import re
from typing import Optional

_PATH_PATTERN = re.compile(r"(?:/[a-zA-Z0-9._-]+)+")
_ENV_VAR_PATTERN = re.compile(
    r"\b(SECRET|KEY|TOKEN|PASSWORD|API_KEY|APP_TOKEN|BOT_TOKEN|"
    r"CREDENTIAL|PRIVATE_KEY|ACCESS_KEY|SIGNING_SECRET)\b",
    re.IGNORECASE,
)
_ENV_VAR_VALUE_PATTERN = re.compile(
    r"(?:SECRET|KEY|TOKEN|PASSWORD|API_KEY|APP_TOKEN|BOT_TOKEN|"
    r"CREDENTIAL|PRIVATE_KEY|ACCESS_KEY|SIGNING_SECRET)\s*[:=]\s*\S+",
    re.IGNORECASE,
)


class ErrorSanitizer:
    MAX_DETAIL_LENGTH = 500

    @staticmethod
    def sanitize(message: str) -> str:
        if not message:
            return message
        result = _ENV_VAR_VALUE_PATTERN.sub(
            lambda m: m.group(0).split("=")[0].split(":")[0] + "=[REDACTED]",
            message,
        )
        result = _ENV_VAR_PATTERN.sub("[REDACTED_KEY]", result)
        result = _PATH_PATTERN.sub("[internal]", result)
        return result

    @staticmethod
    def truncate(message: str, max_length: Optional[int] = None) -> str:
        limit = max_length or ErrorSanitizer.MAX_DETAIL_LENGTH
        if len(message) <= limit:
            return message
        return message[: limit - 20] + "… (truncated)"
