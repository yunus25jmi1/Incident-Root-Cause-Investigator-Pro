import pytest
from investigator.lib.sanitizer import ErrorSanitizer


class TestErrorSanitizer:
    def test_redacts_file_path(self):
        msg = "Error in /home/user/.env: permission denied"
        assert "[internal]" in ErrorSanitizer.sanitize(msg)
        assert "/home/user/.env" not in ErrorSanitizer.sanitize(msg)

    def test_redacts_tmp_path(self):
        msg = "Cannot write to /tmp/coral_abc123/lock"
        sanitized = ErrorSanitizer.sanitize(msg)
        assert "[internal]" in sanitized
        assert "/tmp/coral_abc123/lock" not in sanitized

    def test_redacts_env_var_value(self):
        msg = "NVIDIA_API_KEY=nv-abc123def456"
        sanitized = ErrorSanitizer.sanitize(msg)
        assert "[REDACTED]" in sanitized
        assert "nv-abc123def456" not in sanitized

    def test_redacts_token_pattern(self):
        msg = "Your API_KEY is sk-abc123"
        sanitized = ErrorSanitizer.sanitize(msg)
        assert "[REDACTED_KEY]" in sanitized

    def test_truncates_long_message(self):
        long = "x" * 1000
        truncated = ErrorSanitizer.truncate(long, max_length=50)
        assert len(truncated) <= 50
        assert "truncated" in truncated

    def test_does_not_truncate_short_message(self):
        short = "short error"
        assert ErrorSanitizer.truncate(short, max_length=100) == short

    def test_handles_empty_string(self):
        assert ErrorSanitizer.sanitize("") == ""

    def test_redacts_multiple_patterns(self):
        msg = "Path /var/log/app.log with KEY=supersecret"
        sanitized = ErrorSanitizer.sanitize(msg)
        assert "/var/log/app.log" not in sanitized
        assert "supersecret" not in sanitized
        assert "[internal]" in sanitized
        assert "[REDACTED]" in sanitized

    def test_handles_none(self):
        assert ErrorSanitizer.sanitize("") == ""
