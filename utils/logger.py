import os
import sys
import logging
from flask import request, session, has_request_context

class RequestContextFilter(logging.Filter):
    def filter(self, record):
        if has_request_context():
            from utils.security import get_client_ip
            try:
                record.client_ip = get_client_ip()
            except Exception:
                record.client_ip = getattr(request, "remote_addr", "-") or "-"
            try:
                user_id = session.get("user_id") if session else None
                record.user_id = str(user_id) if user_id else "-"
            except Exception:
                record.user_id = "-"
            record.method = getattr(request, "method", "-")
            record.path = getattr(request, "path", "-")
        else:
            record.client_ip = "-"
            record.user_id = "-"
            record.method = "-"
            record.path = "-"
        return True


class TerminalColorFormatter(logging.Formatter):
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    
    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33;1m",
        "ERROR": "\033[31;1m",
        "CRITICAL": "\033[41;37;1m"
    }

    def __init__(self, use_color=True):
        super().__init__(datefmt="%H:%M:%S")
        self.use_color = use_color

    def format(self, record):
        levelname = record.levelname
        time_str = self.formatTime(record, self.datefmt)
        name = record.name.replace("anvaya.", "")
        client_ip = getattr(record, "client_ip", "-")
        user_id = getattr(record, "user_id", "-")
        context_str = f"[{client_ip}|user:{user_id}]"

        is_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
        force_color = os.getenv("COLOR_LOGS", "1").lower() in ("1", "true", "yes")

        if self.use_color and (is_tty or force_color):
            level_color = self.COLORS.get(levelname, "")
            dim = self.DIM
            reset = self.RESET
            formatted_level = f"{level_color}{levelname:<5}{reset}"
            formatted_time = f"{dim}{time_str}{reset}"
            formatted_name = f"\033[34m{name:<8}\033[0m"
            formatted_context = f"{dim}{context_str}{reset}"
            message = record.getMessage()
            return f"[{formatted_time}] [{formatted_level}] [{formatted_name}] {formatted_context} {message}"
        else:
            return f"[{time_str}] [{levelname:<5}] [{name:<8}] {context_str} {record.getMessage()}"


def setup_logging(app=None):
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.setFormatter(TerminalColorFormatter(use_color=True))
    handler.addFilter(RequestContextFilter())

    root_logger = logging.getLogger("anvaya")
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.propagate = False

    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.setLevel(logging.WARNING)

    if app:
        app.logger.handlers = root_logger.handlers
        app.logger.setLevel(log_level)

    return root_logger


def get_logger(name=None):
    if not name or name == "anvaya":
        return logging.getLogger("anvaya")
    return logging.getLogger(name if name.startswith("anvaya.") else f"anvaya.{name}")
