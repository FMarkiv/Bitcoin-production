"""
Telegram Alerts for BTC Tail Model v10
=======================================
Send trading signals, danger alerts, and execution updates via Telegram.

Setup:
    1. Create a Telegram bot via @BotFather
    2. Get your chat ID by messaging @userinfobot
    3. Set environment variables:
       export TELEGRAM_BOT_TOKEN="your_bot_token"
       export TELEGRAM_CHAT_ID="your_chat_id"

Usage:
    from telegram_alerts import TelegramAlert, MockTelegramAlert

    alert = TelegramAlert()
    alert.send_signal(signal_dict)
    alert.send_danger_alert(danger_data)
"""

import os
import json
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import requests

from logger import get_logger

logger = get_logger(__name__)

# Unicode symbols extracted to avoid f-string backslash issues
CHECK = '\u2713'
CROSS = '\u2717'
ARROW = '\u21b3'
LINE = '\u2501'
BLOCK_FULL = '\u2588'
BLOCK_LIGHT = '\u2591'


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


def _format_hist_context(hist: Optional[dict]) -> str:
    """Format historical context block for any message type."""
    if not hist:
        return f"{ARROW} Historical context unavailable"

    bucket = hist.get('dd_bucket', 'N/A')

    if hist.get('sample_size', 0) < 10:
        return (
            f"\U0001f4ca <b>Historical Context ({bucket})</b>\n"
            f"{ARROW} Insufficient data (n={hist.get('sample_size', 0)})"
        )

    avg_1m = hist.get('avg_1m_return')
    avg_3m = hist.get('avg_3m_return')
    avg_1y = hist.get('avg_1y_return')
    avg_dd = hist.get('avg_1y_max_dd')
    win_1y = hist.get('win_rate_1y')

    hist_avg_parts = []
    if avg_1m is not None:
        hist_avg_parts.append(f"1M: {avg_1m*100:+.1f}%")
    if avg_3m is not None:
        hist_avg_parts.append(f"3M: {avg_3m*100:+.1f}%")
    if avg_1y is not None:
        hist_avg_parts.append(f"1Y: {avg_1y*100:+.1f}%")

    risk_parts = []
    if avg_dd is not None:
        risk_parts.append(f"1Y DD: {avg_dd*100:.1f}%")
    if win_1y is not None:
        risk_parts.append(f"Win: {win_1y*100:.0f}%")

    lines = [f"\U0001f4ca <b>Historical Context ({bucket})</b>"]
    if hist_avg_parts:
        lines.append(f"{ARROW} <b>Hist Avg:</b> {' | '.join(hist_avg_parts)}")
    if risk_parts:
        lines.append(f"{ARROW} <b>Risk:</b> {' | '.join(risk_parts)}")

    return '\n'.join(lines)


def _format_ema(ema_200, above_ema) -> str:
    if ema_200 is None:
        return "EMA 200: N/A"
    status = f"Above {CHECK}" if above_ema else f"Below {CROSS}"
    return f"EMA 200: ${ema_200:,.0f} ({status})"


def _format_mvrv(mvrv, boost_eligible) -> str:
    if mvrv is None:
        return "MVRV: N/A"
    status = "Boost Active" if boost_eligible else "No Boost"
    return f"MVRV: {mvrv:.2f} ({status})"


def _format_dvol(dvol_zscore, dvol_applied=False, base_leverage=None) -> str:
    if dvol_zscore is None:
        return "DVOL Z-Score: N/A"
    line = f"DVOL Z-Score: {dvol_zscore:.2f}"
    if dvol_applied and base_leverage is not None:
        line += f" (reduced from {base_leverage}x)"
    return line


class TelegramAlert:
    """Send alerts via Telegram bot with retry logic."""

    MAX_RETRIES = 3
    BASE_DELAY = 1.0
    API_BASE = "https://api.telegram.org/bot"

    def __init__(self,
                 bot_token: Optional[str] = None,
                 chat_id: Optional[str] = None):
        self.bot_token = bot_token or os.environ.get('TELEGRAM_BOT_TOKEN')
        self.chat_id = chat_id or os.environ.get('TELEGRAM_CHAT_ID')

        if not self.bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN not set - alerts disabled")
        if not self.chat_id:
            logger.warning("TELEGRAM_CHAT_ID not set - alerts disabled")

        self.enabled = bool(self.bot_token and self.chat_id)

        if self.enabled:
            logger.info("Telegram alerts enabled")

    def _api_url(self, method: str) -> str:
        return f"{self.API_BASE}{self.bot_token}/{method}"

    def send_message(self, message: str, parse_mode: str = 'HTML') -> bool:
        """Send a message via Telegram with retry logic."""
        if not self.enabled:
            logger.debug(f"[TELEGRAM DISABLED] Would send: {message[:100]}...")
            return False

        payload = {
            'chat_id': self.chat_id,
            'text': message,
            'parse_mode': parse_mode,
        }

        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                resp = requests.post(
                    self._api_url('sendMessage'),
                    json=payload,
                    timeout=10,
                )
                resp.raise_for_status()
                return resp.json().get('ok', False)
            except requests.RequestException as e:
                last_error = e
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"Telegram send failed (attempt {attempt + 1}): {e}. "
                        f"Retrying in {delay}s..."
                    )
                    time.sleep(delay)

        logger.error(
            f"Failed to send Telegram message after {self.MAX_RETRIES} "
            f"attempts: {last_error}"
        )
        return False

    def send_photo(self, photo_path: str, caption: str = None) -> bool:
        """Send a photo to Telegram."""
        if not self.enabled:
            logger.debug(f"[TELEGRAM DISABLED] Would send photo: {photo_path}")
            return False

        if not os.path.exists(photo_path):
            logger.error(f"Photo not found: {photo_path}")
            return False

        data = {'chat_id': self.chat_id, 'parse_mode': 'HTML'}
        if caption:
            data['caption'] = caption

        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                with open(photo_path, 'rb') as f:
                    resp = requests.post(
                        self._api_url('sendPhoto'),
                        data=data,
                        files={'photo': f},
                        timeout=30,
                    )
                resp.raise_for_status()
                return resp.json().get('ok', False)
            except requests.RequestException as e:
                last_error = e
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"Telegram photo send failed (attempt {attempt + 1}): "
                        f"{e}. Retrying in {delay}s..."
                    )
                    time.sleep(delay)

        logger.error(
            f"Failed to send Telegram photo after {self.MAX_RETRIES} "
            f"attempts: {last_error}"
        )
        return False

    def send_weekly_signal_with_context(
        self,
        signal_data: Dict[str, Any],
        historical_context: dict,
        chart_path: str = None
    ) -> bool:
        """Send weekly signal with historical context and optional chart."""
        ema_200 = signal_data.get('ema_200')
        above_ema = signal_data.get('above_ema_200')

        hist_block = _format_hist_context(historical_context)

        message = (
            f"\U0001f514 <b>BTC TAIL MODEL v10 - WEEKLY SIGNAL</b>\n"
            f"\n"
            f"\U0001f4c5 Date: {signal_data.get('date', 'N/A')}\n"
            f"\U0001f4b0 BTC Price: ${signal_data.get('price', 0):,.0f}\n"
            f"\U0001f4c9 Drawdown: {signal_data.get('drawdown', 0)*100:.1f}%\n"
            f"\n"
            f"<b>SIGNAL: {signal_data.get('position', 'N/A')}</b>\n"
            f"\u26a1 Leverage: {signal_data.get('leverage', 0)}x\n"
            f"{signal_data.get('reasoning', '')}\n"
            f"\n"
            f"{hist_block}\n"
            f"\n"
            f"{LINE*3} Indicators {LINE*3}\n"
            f"\U0001f916 XGBoost Danger: {signal_data.get('prob_left_tail', 0)*100:.1f}%\n"
            f"\U0001f4ca {_format_ema(ema_200, above_ema)}\n"
            f"\U0001f4c8 {_format_mvrv(signal_data.get('mvrv'), signal_data.get('mvrv_boost_eligible'))}\n"
            f"\U0001f321 {_format_dvol(signal_data.get('dvol_zscore'))}\n"
            f"\n"
            f"<i>{_timestamp()}</i>"
        )

        success = self.send_message(message)

        if chart_path and os.path.exists(chart_path):
            bucket = historical_context.get('dd_bucket', 'current') if historical_context else 'current'
            sample = historical_context.get('sample_size', 0) if historical_context else 0
            chart_caption = (
                f"\U0001f4c8 Historical returns from {bucket} drawdown\n"
                f"Based on {sample} historical instances"
            )
            self.send_photo(chart_path, chart_caption)

        return success

    def send_signal(self, signal: Dict[str, Any],
                    historical_context: Optional[dict] = None) -> bool:
        """Send formatted weekly trading signal alert."""
        leverage = signal.get('leverage', 0)
        position = signal.get('position', 'UNKNOWN')

        if leverage == 0:
            emoji = "\U0001f534"  # red circle
        elif leverage >= 5:
            emoji = "\U0001f680"  # rocket
        elif leverage >= 2:
            emoji = "\U0001f4c8"  # chart up
        else:
            emoji = "\u2705"  # check mark

        ema_line = _format_ema(signal.get('ema_200'), signal.get('above_ema_200'))
        mvrv_line = _format_mvrv(signal.get('mvrv'), signal.get('mvrv_boost_eligible', False))
        dvol_line = _format_dvol(
            signal.get('dvol_zscore'),
            signal.get('dvol_filter_applied', False),
            signal.get('base_leverage', leverage),
        )

        hist_block = _format_hist_context(historical_context)

        message = (
            f"{emoji} <b>BTC TAIL MODEL v10 - WEEKLY SIGNAL</b> {emoji}\n"
            f"\n"
            f"<b>Date:</b> {signal.get('date', 'N/A')}\n"
            f"<b>BTC Price:</b> ${signal.get('price', 0):,.2f}\n"
            f"<b>Drawdown:</b> {signal.get('drawdown', 0):.1%}\n"
            f"\n"
            f"<b>SIGNAL: {position}</b>\n"
            f"<b>Leverage: {leverage}x</b>\n"
            f"\n"
            f"<b>Reasoning:</b> {signal.get('reasoning', 'N/A')}\n"
            f"\n"
            f"{hist_block}\n"
            f"\n"
            f"{LINE*3} Indicators {LINE*3}\n"
            f"XGBoost Danger: {signal.get('prob_left_tail', 0):.1%}\n"
            f"{ema_line}\n"
            f"{mvrv_line}\n"
            f"{dvol_line}\n"
            f"Near ATH: {'Yes' if signal.get('near_ath') else 'No'}\n"
            f"ATH Breakout: {'Yes' if signal.get('ath_breakout') else 'No'}\n"
            f"\n"
            f"<i>{_timestamp()}</i>"
        )

        return self.send_message(message)

    def send_danger_alert(self, signal: Dict[str, Any],
                          historical_context: Optional[dict] = None) -> bool:
        """Send IMMEDIATE danger alert when XGBoost probability exceeds threshold."""
        danger_prob = signal.get('prob_left_tail', 0)
        price = signal.get('price', 0)

        hist_block = _format_hist_context(historical_context)

        message = (
            f"\u26a0\ufe0f\u26a0\ufe0f\u26a0\ufe0f <b>DANGER SIGNAL ACTIVATED</b> \u26a0\ufe0f\u26a0\ufe0f\u26a0\ufe0f\n"
            f"\n"
            f"XGBoost Probability: {danger_prob:.1%}\n"
            f"BTC Price: ${price:,.2f}\n"
            f"\n"
            f"<b>ACTION: GO TO CASH IMMEDIATELY</b>\n"
            f"\n"
            f"{hist_block}\n"
            f"\n"
            f"<i>BTC Tail Model v10 - {_timestamp()}</i>"
        )

        return self.send_message(message)

    def send_ath_breakout_alert(self, signal: Dict[str, Any],
                                historical_context: Optional[dict] = None) -> bool:
        """Send alert when ATH breakout signal fires (10x leverage)."""
        price = signal.get('price', 0)

        hist_block = _format_hist_context(historical_context)

        message = (
            f"\U0001f680\U0001f680\U0001f680 <b>ATH BREAKOUT SIGNAL</b> \U0001f680\U0001f680\U0001f680\n"
            f"\n"
            f"BTC Price: ${price:,.2f}\n"
            f"NEW ALL-TIME HIGH after >60% recovery!\n"
            f"\n"
            f"<b>SIGNAL: 10x LEVER</b>\n"
            f"\n"
            f"{hist_block}\n"
            f"\n"
            f"<i>BTC Tail Model v10 - {_timestamp()}</i>"
        )

        return self.send_message(message)

    def send_execution_report(self,
                              signal: Dict[str, Any],
                              execution: Dict[str, Any],
                              success: bool) -> bool:
        """Send execution confirmation."""
        emoji = "\u2705" if success else "\u274c"
        status = "SUCCESS" if success else "FAILED"

        message = (
            f"{emoji} <b>EXECUTION {status}</b> {emoji}\n"
            f"\n"
            f"<b>Target:</b> {signal.get('position', 'N/A')} @ {signal.get('leverage', 0)}x\n"
            f"\n"
            f"<b>Details:</b>\n"
            f"{json.dumps(execution, indent=2, default=str)[:500]}\n"
            f"\n"
            f"<i>{_timestamp()}</i>"
        )

        return self.send_message(message)

    def send_error(self, error: str, context: str = "") -> bool:
        """Send error notification."""
        message = (
            f"\U0001f6a8 <b>ERROR</b> \U0001f6a8\n"
            f"\n"
            f"<b>Context:</b> {context}\n"
            f"<b>Error:</b> {error}\n"
            f"\n"
            f"<i>{_timestamp()}</i>"
        )

        return self.send_message(message)

    def send_heartbeat(self, status: Dict[str, Any]) -> bool:
        """Send periodic heartbeat to confirm bot is running."""
        message = (
            f"\U0001f493 <b>BOT HEARTBEAT</b>\n"
            f"\n"
            f"<b>Status:</b> Running\n"
            f"<b>Last Signal:</b> {status.get('last_signal_time', 'N/A')}\n"
            f"<b>Current Position:</b> {status.get('current_position', 'N/A')}\n"
            f"<b>Account Value:</b> ${status.get('account_value', 0):,.2f}\n"
            f"\n"
            f"<i>{_timestamp()}</i>"
        )

        return self.send_message(message)

    def send_daily_execution(self,
                             leverage_change: float,
                             new_leverage: float,
                             target_leverage: float,
                             remaining_delta: float,
                             success: bool) -> bool:
        """Send daily execution update for diversified deployment mode."""
        emoji = "\u2705" if success else "\u274c"
        status = "SUCCESS" if success else "FAILED"

        # Progress bar
        if target_leverage > 0:
            progress_pct = min(100, max(0, (new_leverage / target_leverage) * 100))
            filled = int(progress_pct / 10)
            bar = BLOCK_FULL * filled + BLOCK_LIGHT * (10 - filled)
        else:
            progress_pct = 100
            bar = BLOCK_FULL * 10

        message = (
            f"{emoji} <b>DAILY EXECUTION {status}</b>\n"
            f"\n"
            f"<b>Today's Change:</b> {leverage_change:+.3f}x\n"
            f"<b>Current Leverage:</b> {new_leverage:.2f}x\n"
            f"<b>Target Leverage:</b> {target_leverage:.1f}x\n"
            f"<b>Remaining:</b> {remaining_delta:+.3f}x\n"
            f"\n"
            f"<b>Progress:</b> [{bar}] {progress_pct:.0f}%\n"
            f"\n"
            f"<i>{_timestamp()}</i>"
        )

        return self.send_message(message)

    def send_status(self, status_data: Dict[str, Any],
                    historical_context: Optional[dict] = None) -> bool:
        """Send on-demand status report."""
        hist_block = _format_hist_context(historical_context)

        message = (
            f"\U0001f4cb <b>STATUS REPORT</b>\n"
            f"\n"
            f"<b>BTC Price:</b> ${status_data.get('price', 0):,.2f}\n"
            f"<b>Position:</b> {status_data.get('position', 'N/A')}\n"
            f"<b>Leverage:</b> {status_data.get('leverage', 0)}x\n"
            f"<b>Drawdown:</b> {status_data.get('drawdown', 0):.1%}\n"
            f"<b>Account Value:</b> ${status_data.get('account_value', 0):,.2f}\n"
            f"<b>Danger Prob:</b> {status_data.get('danger_prob', 0):.1%}\n"
            f"\n"
            f"{hist_block}\n"
            f"\n"
            f"<i>{_timestamp()}</i>"
        )

        return self.send_message(message)


class MockTelegramAlert:
    """Mock alert for testing - same interface, prints to stdout."""

    def __init__(self):
        self.enabled = True
        self.messages = []
        logger.info("MockTelegramAlert initialized (no real messages)")

    def _record(self, label: str, message: str) -> bool:
        self.messages.append({'label': label, 'message': message})
        logger.info(f"[MOCK TELEGRAM] {label}: {message[:80]}...")
        return True

    def send_message(self, message: str, parse_mode: str = 'HTML') -> bool:
        return self._record("message", message)

    def send_photo(self, photo_path: str, caption: str = None) -> bool:
        return self._record("photo", f"{photo_path}: {caption or ''}")

    def send_weekly_signal_with_context(self, signal_data: Dict[str, Any],
                                        historical_context: dict,
                                        chart_path: str = None) -> bool:
        return self._record(
            "signal_with_context",
            f"{signal_data.get('position')} @ {signal_data.get('leverage')}x "
            f"(hist: {historical_context.get('dd_bucket', 'N/A') if historical_context else 'N/A'})"
        )

    def send_signal(self, signal: Dict[str, Any],
                    historical_context: Optional[dict] = None) -> bool:
        return self._record("signal", f"{signal.get('position')} @ {signal.get('leverage')}x")

    def send_danger_alert(self, signal: Dict[str, Any],
                          historical_context: Optional[dict] = None) -> bool:
        return self._record("danger", f"prob={signal.get('prob_left_tail', 0):.1%}")

    def send_ath_breakout_alert(self, signal: Dict[str, Any],
                                historical_context: Optional[dict] = None) -> bool:
        return self._record("ath_breakout", f"price=${signal.get('price', 0):,.0f}")

    def send_execution_report(self, signal, execution, success) -> bool:
        return self._record("execution", f"{'SUCCESS' if success else 'FAILED'}")

    def send_error(self, error: str, context: str = "") -> bool:
        return self._record("error", f"{context}: {error}")

    def send_heartbeat(self, status: Dict[str, Any]) -> bool:
        return self._record("heartbeat", "alive")

    def send_daily_execution(self, leverage_change, new_leverage,
                             target_leverage, remaining_delta, success) -> bool:
        return self._record("daily", f"{leverage_change:+.3f}x -> {new_leverage:.2f}x")

    def send_status(self, status_data: Dict[str, Any],
                    historical_context: Optional[dict] = None) -> bool:
        return self._record("status", f"{status_data.get('position', 'N/A')}")


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Telegram Alerts for BTC Tail Model v10')
    parser.add_argument('--mock', action='store_true', help='Use mock alerts')
    parser.add_argument('--test', action='store_true', help='Send test message')

    args = parser.parse_args()

    if args.mock:
        alert = MockTelegramAlert()
    else:
        alert = TelegramAlert()

    if args.test:
        test_signal = {
            'date': '2026-03-05',
            'price': 92861.02,
            'drawdown': -0.256,
            'prob_left_tail': 0.023,
            'near_ath': False,
            'ath_breakout': False,
            'vol_high': False,
            'leverage': 1,
            'position': '1x LONG',
            'reasoning': 'Middle zone (DD=-25.6%) - stay invested',
            'ema_200': 45000,
            'above_ema_200': True,
            'mvrv': 2.5,
            'mvrv_boost_eligible': True,
            'dvol_zscore': 0.15,
        }

        test_hist = {
            'dd_bucket': '-30% to -25%',
            'sample_size': 42,
            'avg_1m_return': 0.007,
            'avg_3m_return': 0.024,
            'avg_1y_return': 0.078,
            'avg_1y_max_dd': -0.124,
            'win_rate_1y': 0.68,
        }

        success = alert.send_signal(test_signal, historical_context=test_hist)
        print(f"Test signal sent: {success}")
    else:
        print("Use --test to send a test message")
        print("Use --mock to test without actually sending")
