"""claude-log-doctor: self-healing log watchdog for Python services."""
from .classifier import Classifier
from .config import Config
from .loop import run_forever, run_once
from .notifier import ConsoleNotifier, Notifier, SlackNotifier, TelegramNotifier, make_default_notifier
from .repair import apply_pending, repair_event, rollback_last

__all__ = [
    "Config",
    "Classifier",
    "Notifier",
    "ConsoleNotifier",
    "TelegramNotifier",
    "SlackNotifier",
    "make_default_notifier",
    "run_once",
    "run_forever",
    "repair_event",
    "apply_pending",
    "rollback_last",
]
__version__ = "0.1.0"
