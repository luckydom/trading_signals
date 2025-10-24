"""Configuration management utilities."""

import os
from pathlib import Path
from typing import Any, Dict
import yaml
from dotenv import load_dotenv


class Config:
    """Configuration manager for the trading system."""

    def __init__(self, config_path: str = "config.yaml", env_path: str = ".env"):
        """Initialize configuration from YAML and environment files."""
        # Check if .env exists and load it
        if not Path(env_path).exists():
            raise FileNotFoundError(
                f"\n{'='*60}\n"
                f"ERROR: Environment file '{env_path}' not found!\n"
                f"{'='*60}\n"
                f"Please create it by copying .env.example:\n"
                f"  cp .env.example .env\n"
                f"Then edit it with your API keys and settings.\n"
                f"{'='*60}"
            )

        load_dotenv(env_path)

        # Load YAML configuration
        self.config = self._load_yaml(config_path)

        # Override with environment variables
        self._apply_env_overrides()

        # Validate configuration
        self._validate_config()

    def _load_yaml(self, path: str) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        if not Path(path).exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")

        with open(path, 'r') as f:
            return yaml.safe_load(f)

    def _apply_env_overrides(self):
        """Apply environment variable overrides to configuration."""
        # Exchange credentials
        if os.getenv("API_KEY"):
            self.config.setdefault("exchange_credentials", {})
            self.config["exchange_credentials"]["api_key"] = os.getenv("API_KEY")

        if os.getenv("API_SECRET"):
            self.config.setdefault("exchange_credentials", {})
            self.config["exchange_credentials"]["api_secret"] = os.getenv("API_SECRET")

        # Notification webhooks
        if os.getenv("NOTIFY_SLACK_WEBHOOK"):
            self.config.setdefault("notifications", {})
            self.config["notifications"]["slack_webhook"] = os.getenv("NOTIFY_SLACK_WEBHOOK")
        if os.getenv("NOTIFY_DISCORD_WEBHOOK"):
            self.config.setdefault("notifications", {})
            self.config["notifications"]["discord_webhook"] = os.getenv("NOTIFY_DISCORD_WEBHOOK")

        if os.getenv("NOTIFY_TELEGRAM_TOKEN"):
            self.config.setdefault("notifications", {})
            self.config["notifications"]["telegram_token"] = os.getenv("NOTIFY_TELEGRAM_TOKEN")

        if os.getenv("NOTIFY_TELEGRAM_CHAT_ID"):
            self.config.setdefault("notifications", {})
            self.config["notifications"]["telegram_chat_id"] = os.getenv("NOTIFY_TELEGRAM_CHAT_ID")

        # Email/SMTP support removed per user request

    def _validate_config(self):
        """Validate required configuration settings."""
        # Skip validation in development mode
        if os.getenv("DEV_MODE") == "true":
            print("⚠️  Running in DEVELOPMENT MODE - API validation skipped")
            return

        errors = []

        # Check for API credentials (optional but warn if missing)
        if not os.getenv("API_KEY") or os.getenv("API_KEY") == "your_api_key_here":
            errors.append("API_KEY not set or still has default value")

        if not os.getenv("API_SECRET") or os.getenv("API_SECRET") == "your_api_secret_here":
            errors.append("API_SECRET not set or still has default value")

        # Check exchange configuration
        if not self.config.get("exchange"):
            errors.append("Exchange not configured in config.yaml")

        if errors:
            error_msg = (
                f"\n{'='*60}\n"
                f"CONFIGURATION ERRORS:\n"
                f"{'='*60}\n"
            )
            for error in errors:
                error_msg += f"  ❌ {error}\n"
            error_msg += (
                f"{'='*60}\n"
                f"Please edit .env file with your actual credentials.\n"
                f"Or set DEV_MODE=true in .env to skip validation.\n"
                f"{'='*60}"
            )
            raise ValueError(error_msg)

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by dot-notation key."""
        keys = key.split('.')
        value = self.config

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default

        return value

    def __getitem__(self, key: str) -> Any:
        """Allow dictionary-style access."""
        return self.get(key)

    def __repr__(self) -> str:
        """String representation of configuration."""
        # Hide sensitive information
        safe_config = self.config.copy()
        if "exchange_credentials" in safe_config:
            safe_config["exchange_credentials"] = "**HIDDEN**"
        if "notifications" in safe_config:
            if "slack_webhook" in safe_config["notifications"]:
                safe_config["notifications"]["slack_webhook"] = "**HIDDEN**"
            if "telegram_token" in safe_config["notifications"]:
                safe_config["notifications"]["telegram_token"] = "**HIDDEN**"

        return f"Config({safe_config})"


# Global configuration instance
_config = None

def get_config(config_path: str = "config.yaml", env_path: str = ".env") -> Config:
    """Get singleton configuration instance."""
    global _config
    if _config is None:
        _config = Config(config_path, env_path)
    return _config
