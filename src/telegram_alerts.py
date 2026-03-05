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
import io
import json
import time
import email.generator
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from logger import get_logger

logger = get_logger(__name__)


class TelegramAlert:
    """Send alerts via Telegram bot with retry logic."""

    MAX_RETRIES = 3
    BASE_DELAY = 1.0

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

    def send_message(self, message: str, parse_mode: str = 'HTML') -> bool:
        """Send a message via Telegram with retry logic."""
        if not self.enabled:
            logger.debug(f"[TELEGRAM DISABLED] Would send: {message[:100]}...")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        data = urllib.parse.urlencode({
            'chat_id': self.chat_id,
            'text': message,
            'parse_mode': parse_mode,
        }).encode('utf-8')

        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                request = urllib.request.Request(url, data=data)
                response = urllib.request.urlopen(request, timeout=10)
                result = json.loads(response.read().decode('utf-8'))
                return result.get('ok', False)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                    ConnectionError, OSError) as e:
                last_error = e
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.BASE_DELAY * (2 ** attempt)
                    logger.warning(f"Telegram send failed (attempt {attempt + 1}): {e}. Retrying in {delay}s...")
                    time.sleep(delay)

        logger.error(f"Failed to send Telegram message after {self.MAX_RETRIES} attempts: {last_error}")
        return False

    def send_photo(self, photo_path: str, caption: str = None) -> bool:
        """Send a photo to Telegram using multipart form upload."""
        if not self.enabled:
            logger.debug(f"[TELEGRAM DISABLED] Would send photo: {photo_path}")
            return False

        if not os.path.exists(photo_path):
            logger.error(f"Photo not found: {photo_path}")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"

        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                # Build multipart form data
                boundary = '----FormBoundary' + hex(int(time.time() * 1000))[2:]
                body = io.BytesIO()

                # chat_id field
                body.write(f'--{boundary}\r\n'.encode())
                body.write(b'Content-Disposition: form-data; name="chat_id"\r\n\r\n')
                body.write(f'{self.chat_id}\r\n'.encode())

                # parse_mode field
                body.write(f'--{boundary}\r\n'.encode())
                body.write(b'Content-Disposition: form-data; name="parse_mode"\r\n\r\n')
                body.write(b'HTML\r\n')

                # caption field
                if caption:
                    body.write(f'--{boundary}\r\n'.encode())
                    body.write(b'Content-Disposition: form-data; name="caption"\r\n\r\n')
                    body.write(f'{caption}\r\n'.encode())

                # photo file
                filename = os.path.basename(photo_path)
                body.write(f'--{boundary}\r\n'.encode())
                body.write(f'Content-Disposition: form-data; name="photo"; filename="{filename}"\r\n'.encode())
                body.write(b'Content-Type: image/png\r\n\r\n')
                with open(photo_path, 'rb') as f:
                    body.write(f.read())
                body.write(b'\r\n')

                body.write(f'--{boundary}--\r\n'.encode())

                data = body.getvalue()
                request = urllib.request.Request(url, data=data)
                request.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')

                response = urllib.request.urlopen(request, timeout=30)
                result = json.loads(response.read().decode('utf-8'))
                return result.get('ok', False)

            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                    ConnectionError, OSError) as e:
                last_error = e
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.BASE_DELAY * (2 ** attempt)
                    logger.warning(f"Telegram photo send failed (attempt {attempt + 1}): {e}. Retrying in {delay}s...")
                    time.sleep(delay)

        logger.error(f"Failed to send Telegram photo after {self.MAX_RETRIES} attempts: {last_error}")
        return False

    def send_weekly_signal_with_context(
        self,
        signal_data: Dict[str, Any],
        historical_context: dict,
        chart_path: str = None
    ) -> bool:
        """Send weekly signal with historical context and optional chart."""
        hist = historical_context

        if hist and hist.get('sample_size', 0) >= 10:
            avg_1m = hist.get('avg_1m_return')
            avg_3m = hist.get('avg_3m_return')
            avg_1y = hist.get('avg_1y_return')
            avg_1y_dd = hist.get('avg_1y_max_dd')
            win_1y = hist.get('win_rate_1y')

            fmt_1m = f"{avg_1m*100:+.1f}%" if avg_1m is not None else "N/A"
            fmt_3m = f"{avg_3m*100:+.1f}%" if avg_3m is not None else "N/A"
            fmt_1y = f"{avg_1y*100:+.1f}%" if avg_1y is not None else "N/A"
            fmt_dd = f"{avg_1y_dd*100:.1f}%" if avg_1y_dd is not None else "N/A"
            fmt_win = f"{win_1y*100:.0f}%" if win_1y is not None else "N/A"

            hist_line = (
                f"\u21b3 <b>Hist Avg:</b> "
                f"1M: {fmt_1m} | "
                f"3M: {fmt_3m} | "
                f"1Y: {fmt_1y}\n"
                f"\u21b3 <b>Risk:</b> "
                f"1Y DD: {fmt_dd} | "
                f"Win: {fmt_win}"
            )
        elif hist:
            hist_line = f"\u21b3 Insufficient historical data (n={hist.get('sample_size', 0)})"
        else:
            hist_line = "\u21b3 Historical context unavailable"

        # EMA info
        ema_200 = signal_data.get('ema_200')
        above_ema = signal_data.get('above_ema_200')

        ema_line = ""
        if ema_200:
            ema_status = 'Above \u2713' if above_ema else 'Below \u2717'
            ema_line = f"\U0001f4ca EMA 200: ${ema_200:,.0f} ({ema_status})\n"

        mvrv_status = 'Boost \u2713' if signal_data.get('mvrv_boost_eligible') else 'No Boost'

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
            f"<b>\U0001f4ca Historical Context ({hist.get('dd_bucket', 'N/A') if hist else 'N/A'})</b>\n"
            f"{hist_line}\n"
            f"\n"
            f"\u2501\u2501\u2501 Indicators \u2501\u2501\u2501\n"
            f"\U0001f916 XGBoost Danger: {signal_data.get('prob_left_tail', 0)*100:.1f}%\n"
            f"{ema_line}"
            f"\U0001f4c8 MVRV: {signal_data.get('mvrv', 0):.2f} ({mvrv_status})\n"
            f"\U0001f321 DVOL Z-Score: {signal_data.get('dvol_zscore', 0):.2f}"
        )

        success = self.send_message(message)

        if chart_path and os.path.exists(chart_path):
            chart_caption = (
                f"\U0001f4c8 Historical returns from {hist.get('dd_bucket', 'current') if hist else 'current'} drawdown\n"
                f"Based on {hist.get('sample_size', 0) if hist else 0} historical instances"
            )
            self.send_photo(chart_path, chart_caption)

        return success

    def send_signal(self, signal: Dict[str, Any]) -> bool:
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

        # EMA info
        ema_200 = signal.get('ema_200')
        above_ema = signal.get('above_ema_200')
        if ema_200 is not None:
            ema_line = f"EMA 200: ${ema_200:,.0f} ({'Above' if above_ema else 'Below'})"
        else:
            ema_line = "EMA 200: N/A"

        # MVRV info
        mvrv = signal.get('mvrv')
        mvrv_boost = signal.get('mvrv_boost_eligible', False)
        if mvrv is not None:
            mvrv_line = f"MVRV: {mvrv:.2f} ({'Boost Active' if mvrv_boost else 'No Boost'})"
        else:
            mvrv_line = "MVRV: N/A"

        # DVOL info
        dvol_zscore = signal.get('dvol_zscore')
        dvol_applied = signal.get('dvol_filter_applied', False)
        if dvol_zscore is not None:
            dvol_line = f"DVOL Z-Score: {dvol_zscore:.2f}"
            if dvol_applied:
                dvol_line += f" (reduced from {signal.get('base_leverage', leverage)}x)"
        else:
            dvol_line = "DVOL Z-Score: N/A"

        danger_prob = signal.get('prob_left_tail', 0)

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
            f"--- Indicators ---\n"
            f"XGBoost Danger: {danger_prob:.1%}\n"
            f"{ema_line}\n"
            f"{mvrv_line}\n"
            f"{dvol_line}\n"
            f"Near ATH: {'Yes' if signal.get('near_ath') else 'No'}\n"
            f"ATH Breakout: {'Yes' if signal.get('ath_breakout') else 'No'}\n"
            f"\n"
            f"<i>Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</i>"
        )

        return self.send_message(message)

    def send_danger_alert(self, signal: Dict[str, Any]) -> bool:
        """Send IMMEDIATE danger alert when XGBoost probability exceeds threshold."""
        danger_prob = signal.get('prob_left_tail', 0)
        price = signal.get('price', 0)

        message = (
            f"\u26a0\ufe0f\u26a0\ufe0f\u26a0\ufe0f <b>DANGER SIGNAL ACTIVATED</b> \u26a0\ufe0f\u26a0\ufe0f\u26a0\ufe0f\n"
            f"\n"
            f"XGBoost Probability: {danger_prob:.1%}\n"
            f"BTC Price: ${price:,.2f}\n"
            f"\n"
            f"<b>ACTION: GO TO CASH IMMEDIATELY</b>\n"
            f"\n"
            f"<i>BTC Tail Model v10 - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</i>"
        )

        return self.send_message(message)

    def send_ath_breakout_alert(self, signal: Dict[str, Any]) -> bool:
        """Send alert when ATH breakout signal fires (10x leverage)."""
        price = signal.get('price', 0)

        message = (
            f"\U0001f680\U0001f680\U0001f680 <b>ATH BREAKOUT SIGNAL</b> \U0001f680\U0001f680\U0001f680\n"
            f"\n"
            f"BTC Price: ${price:,.2f}\n"
            f"NEW ALL-TIME HIGH after >60% recovery!\n"
            f"\n"
            f"<b>SIGNAL: 10x LEVER</b>\n"
            f"\n"
            f"<i>BTC Tail Model v10 - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</i>"
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
            f"<i>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</i>"
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
            f"<i>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</i>"
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
            f"<i>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</i>"
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
            bar = "\u2588" * filled + "\u2591" * (10 - filled)
        else:
            progress_pct = 100
            bar = "\u2588" * 10

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
            f"<i>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</i>"
        )

        return self.send_message(message)

    def send_status(self, status_data: Dict[str, Any]) -> bool:
        """Send on-demand status report."""
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
            f"<i>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</i>"
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
        return self._record("signal_with_context",
                          f"{signal_data.get('position')} @ {signal_data.get('leverage')}x "
                          f"(hist: {historical_context.get('dd_bucket', 'N/A') if historical_context else 'N/A'})")

    def send_signal(self, signal: Dict[str, Any]) -> bool:
        return self._record("signal", f"{signal.get('position')} @ {signal.get('leverage')}x")

    def send_danger_alert(self, signal: Dict[str, Any]) -> bool:
        return self._record("danger", f"prob={signal.get('prob_left_tail', 0):.1%}")

    def send_ath_breakout_alert(self, signal: Dict[str, Any]) -> bool:
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

    def send_status(self, status_data: Dict[str, Any]) -> bool:
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
        }

        success = alert.send_signal(test_signal)
        print(f"Test signal sent: {success}")
    else:
        print("Use --test to send a test message")
        print("Use --mock to test without actually sending")
