"""Notification system for trade signals."""

import json
import requests
from datetime import datetime, timezone
from typing import Optional
import logging

from src.strategy.state import TradingSignal, SignalType
from src.strategy.sizing import PositionSize


class NotificationManager:
    """Manage notifications to Slack, Telegram, etc."""

    def __init__(self, config):
        """Initialize notification manager."""
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Notification settings
        self.enabled = config.get("notifications.enabled", True)
        self.slack_enabled = config.get("notifications.slack_enabled", True)
        self.slack_webhook = config.get("notifications.slack_webhook")
        self.telegram_enabled = config.get("notifications.telegram_enabled", False)
        self.telegram_token = config.get("notifications.telegram_token")
        self.telegram_chat_id = config.get("notifications.telegram_chat_id")
        # Discord (optional)
        self.discord_webhook = config.get("notifications.discord_webhook")

        # Debounce settings
        self.last_notification_time = None
        self.debounce_minutes = config.get("notifications.debounce_minutes", 5)

    def send_trade_signal(
        self,
        signal: TradingSignal,
        position_size: PositionSize,
        ticket_text: Optional[str] = None
    ) -> bool:
        """
        Send trade signal notification.

        Args:
            signal: Trading signal
            position_size: Position sizing information

        Returns:
            Success status
        """
        if not self.enabled:
            self.logger.info("Notifications disabled")
            return False

        # Check debounce
        if not self._check_debounce():
            self.logger.info("Notification debounced")
            return False

        # Format message
        message = self._format_message(signal, position_size)

        # Send to enabled channels
        success = True
        if self.slack_enabled and self.slack_webhook:
            success = success and self._send_slack(message)

        if self.telegram_enabled and self.telegram_token and self.telegram_chat_id:
            success = success and self._send_telegram(message)

        # Discord webhook
        if self.discord_webhook:
            text = ticket_text or message
            success = success and self._send_discord(text)

        # Update last notification time
        if success:
            self.last_notification_time = datetime.now(timezone.utc)

        return success

    def _check_debounce(self) -> bool:
        """Check if enough time has passed since last notification."""
        if not self.last_notification_time:
            return True

        elapsed = datetime.now(timezone.utc) - self.last_notification_time
        return elapsed.total_seconds() > (self.debounce_minutes * 60)

    def _format_message(
        self,
        signal: TradingSignal,
        position_size: PositionSize
    ) -> str:
        """Format notification message."""
        # Determine action emoji and text
        if signal.signal_type == SignalType.ENTER_LONG_SPREAD:
            emoji = "📈"
            action = "LONG SPREAD"
        elif signal.signal_type == SignalType.ENTER_SHORT_SPREAD:
            emoji = "📉"
            action = "SHORT SPREAD"
        elif signal.signal_type == SignalType.EXIT_POSITION:
            emoji = "✅"
            action = "EXIT POSITION"
        elif signal.signal_type == SignalType.STOP_LOSS:
            emoji = "🛑"
            action = "STOP LOSS"
        else:
            emoji = "ℹ️"
            action = "INFO"

        # Build message
        lines = [
            f"{emoji} *BTC-ETH Stat Arb Signal*",
            f"*Action:* {action}",
            f"*Z-score:* {signal.zscore:.3f}",
            f"*Beta:* {signal.beta:.3f}",
            "",
            f"*Positions:*",
            f"• ETH: ${position_size.eth_notional_usd:,.0f}",
            f"• BTC: ${position_size.btc_notional_usd:,.0f}",
            "",
            f"*Reason:* {signal.reason}",
            f"*Time:* {signal.timestamp.strftime('%Y-%m-%d %H:%M UTC')}"
        ]

        return "\n".join(lines)

    def _send_slack(self, message: str) -> bool:
        """Send message to Slack."""
        try:
            payload = {
                "text": message,
                "username": "Trading Bot",
                "icon_emoji": ":chart_with_upwards_trend:"
            }

            response = requests.post(
                self.slack_webhook,
                json=payload,
                timeout=10
            )

            if response.status_code == 200:
                self.logger.info("Slack notification sent")
                return True
            else:
                self.logger.error(f"Slack error: {response.status_code}")
                return False

        except Exception as e:
            self.logger.error(f"Slack notification failed: {e}")
            return False

    def _send_telegram(self, message: str) -> bool:
        """Send message to Telegram."""
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"

            payload = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }

            response = requests.post(url, json=payload, timeout=10)

            if response.status_code == 200:
                self.logger.info("Telegram notification sent")
                return True
            else:
                self.logger.error(f"Telegram error: {response.status_code}")
                return False

        except Exception as e:
            self.logger.error(f"Telegram notification failed: {e}")
            return False

    def _send_discord(self, content: str) -> bool:
        """Send a message to Discord via incoming webhook."""
        try:
            resp = requests.post(self.discord_webhook, json={"content": content}, timeout=10)
            if resp.status_code in (200, 204):
                self.logger.info("Discord notification sent")
                return True
            self.logger.error(f"Discord error: {resp.status_code} {resp.text}")
            return False
        except Exception as e:
            self.logger.error(f"Discord notification failed: {e}")
            return False

    def send_error_notification(self, error_message: str) -> bool:
        """Send error notification."""
        if not self.enabled:
            return False

        message = f"⚠️ *Trading System Error*\n\n{error_message}\n\n_Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_"

        success = True
        if self.slack_enabled and self.slack_webhook:
            success = success and self._send_slack(message)

        if self.telegram_enabled and self.telegram_token:
            success = success and self._send_telegram(message)

        if self.discord_webhook:
            success = success and self._send_discord(message)

        return success
