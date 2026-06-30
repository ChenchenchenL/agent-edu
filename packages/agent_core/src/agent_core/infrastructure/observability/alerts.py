from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class AlertDispatcher:
    """Dispatches critical alerts to a log file and optional webhook.

    For MVP, this provides a minimal notification channel so that critical
    events are not silently lost. The log file can be monitored by any
    log aggregation tool, and the webhook can notify Slack / DingTalk / etc.
    """

    def __init__(
        self,
        *,
        alert_log_path: str | None = None,
        webhook_url: str | None = None,
    ) -> None:
        self._log_path = Path(alert_log_path) if alert_log_path else None
        self._webhook_url = webhook_url
        if self._log_path is not None:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def dispatch(self, *, alert_name: str, severity: str, message: str, details: dict | None = None) -> None:
        entry = {
            "timestamp": time.time(),
            "alert_name": alert_name,
            "severity": severity,
            "message": message,
            "details": details or {},
        }
        self._write_log(entry)
        self._send_webhook(entry)

    def _write_log(self, entry: dict) -> None:
        if self._log_path is None:
            logger.warning("[ALERT] %s (%s): %s", entry["alert_name"], entry["severity"], entry["message"])
            return
        try:
            with open(self._log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            logger.warning("[ALERT] %s (%s): %s", entry["alert_name"], entry["severity"], entry["message"])

    def _send_webhook(self, entry: dict) -> None:
        if not self._webhook_url:
            return
        try:
            import httpx
            with httpx.Client(timeout=5.0) as client:
                client.post(self._webhook_url, json=entry)
        except Exception:
            logger.warning("Failed to send alert webhook for %s", entry["alert_name"])
