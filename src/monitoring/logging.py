"""
Structured Logging Configuration
==================================
Sets up JSON-format logging for production use.

Features:
- Console output (human-readable)
- File output (JSON format for parsing/aggregation)
- Automatic log rotation when files get large
- Structured context (request_id, endpoint, user_agent)
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
"""

import logging
import logging.handlers
import json
from typing import Optional, Dict, Any
from pathlib import Path
from datetime import datetime
import os


class JSONFormatter(logging.Formatter):
    """Custom formatter that outputs JSON-structured logs."""

    def format(self, record: logging.LogRecord) -> str:
        """Format as JSON with all relevant fields."""
        log_obj = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Include exception info if present
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        
        # Include extra fields (set via logger.info(..., extra={...}))
        for key, value in record.__dict__.items():
            if key not in [
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "thread",
                "threadName",
                "exc_info",
                "exc_text",
                "stack_info",
                "getMessage",
            ]:
                log_obj[key] = value
        
        return json.dumps(log_obj)


class HumanReadableFormatter(logging.Formatter):
    """Simple human-readable formatter for console."""

    FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    def __init__(self):
        super().__init__(self.FORMAT, datefmt="%Y-%m-%d %H:%M:%S")


def setup_logging(
    log_dir: Optional[Path] = None,
    log_level: str = "INFO",
    enable_json_file: bool = True,
    enable_console: bool = True,
    console_level: str = "INFO",
) -> logging.Logger:
    """
    Configure structured logging for the application.

    Args:
        log_dir: Directory for log files. If None, logs only to console.
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        enable_json_file: Whether to write JSON logs to file
        enable_console: Whether to output to console
        console_level: Console log level (may be different from file level)

    Returns:
        Configured root logger
    """
    # Create logs directory if needed
    if log_dir and enable_json_file:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # Remove any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Console handler (human-readable)
    if enable_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, console_level.upper()))
        console_handler.setFormatter(HumanReadableFormatter())
        root_logger.addHandler(console_handler)
    
    # File handler (JSON, rotating)
    if log_dir and enable_json_file:
        file_path = log_dir / "eDNA_api.log"
        
        # Rotating file handler: 10 MB per file, keep 5 backups
        file_handler = logging.handlers.RotatingFileHandler(
            file_path,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
        )
        file_handler.setLevel(getattr(logging, log_level.upper()))
        file_handler.setFormatter(JSONFormatter())
        root_logger.addHandler(file_handler)
    
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the given name."""
    return logging.getLogger(name)


# Context logger for request-scoped logging
class RequestContext:
    """
    Context manager for request-scoped logging.
    
    Usage:
        with RequestContext(request_id="req-123", endpoint="/run/single"):
            logger.info("Processing request")  # Will include request_id & endpoint
    """

    _thread_local = None

    def __init__(
        self,
        request_id: Optional[str] = None,
        endpoint: Optional[str] = None,
        user_agent: Optional[str] = None,
        **kwargs,
    ):
        self.context = {
            "request_id": request_id,
            "endpoint": endpoint,
            "user_agent": user_agent,
        }
        self.context.update(kwargs)

    def __enter__(self):
        """Enter context and store in thread-local storage."""
        if RequestContext._thread_local is None:
            import threading
            RequestContext._thread_local = threading.local()
        
        RequestContext._thread_local.context = self.context
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context and clear thread-local storage."""
        if RequestContext._thread_local:
            RequestContext._thread_local.context = None
        return False

    @staticmethod
    def get_context() -> Dict[str, Any]:
        """Get current request context (if one is active)."""
        if RequestContext._thread_local is None:
            return {}
        
        context = getattr(RequestContext._thread_local, "context", None)
        return context or {}


# Monkey-patch logging.LoggerAdapter to use request context
class ContextualLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that includes request context in all logs."""

    def process(self, msg, kwargs):
        """Add request context to the log record."""
        context = RequestContext.get_context()
        
        if context:
            extra = kwargs.get("extra", {})
            extra.update(context)
            kwargs["extra"] = extra
        
        return msg, kwargs


def get_contextual_logger(name: str) -> ContextualLoggerAdapter:
    """Get a logger that includes request context in all messages."""
    logger = logging.getLogger(name)
    return ContextualLoggerAdapter(logger, {})


# Initialize logging on import
_log_dir = Path(os.getenv("EDNALPT_LOG_DIR", "logs"))
if not logging.getLogger().handlers:  # Only if not already configured
    setup_logging(
        log_dir=_log_dir,
        log_level=os.getenv("EDNALPT_LOG_LEVEL", "INFO"),
        enable_json_file=True,
        enable_console=True,
    )

# Example usage:
if __name__ == "__main__":
    logger = get_contextual_logger(__name__)
    
    # Example: log without context
    logger.info("Server starting...")
    
    # Example: log within request context
    with RequestContext(request_id="req-001", endpoint="/health"):
        logger.info("Health check invoked")
    
    # Example: log with exception
    try:
        1 / 0
    except ZeroDivisionError:
        logger.error("Math error occurred", exc_info=True)
