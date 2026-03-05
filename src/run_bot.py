"""
BTC Tail Model Trading Bot v10
==============================
Main orchestrator that:
1. Fetches latest BTC data
2. Generates trading signal
3. Executes on Hyperliquid
4. Sends Telegram alerts

Usage:
    # Run once (for cron jobs)
    python run_bot.py --once

    # Run continuously (checks every hour)
    python run_bot.py --continuous

    # Dry run (no actual trades)
    python run_bot.py --dry-run

    # Mock everything (for testing)
    python run_bot.py --mock

Environment Variables Required:
    HL_PRIVATE_KEY      - Hyperliquid wallet private key
    TELEGRAM_BOT_TOKEN  - Telegram bot token
    TELEGRAM_CHAT_ID    - Your Telegram chat ID

Optional:
    BTC_DATA_PATH       - Path to BTC CSV data (default: auto-fetch)
    CHECK_INTERVAL      - Hours between checks (default: 1)
"""

import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# v9 import - Updated from v8_production
from v9_production import generate_signal, load_btc_data, compute_features, create_weekly_data, fetch_dvol_data


# ============================================================================
# RETRY HELPER
# ============================================================================

def retry_with_backoff(func, max_retries: int = 3, base_delay: float = 1.0,
                       exceptions: tuple = (Exception,)):
    """
    Retry a function with exponential backoff.

    Args:
        func: Callable to retry
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds (doubles each retry)
        exceptions: Tuple of exceptions to catch and retry

    Returns:
        Result of func() if successful

    Raises:
        Last exception if all retries exhausted
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return func()
        except exceptions as e:
            last_exception = e
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                print(f"  Attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                time.sleep(delay)
            else:
                print(f"  All {max_retries + 1} attempts failed")

    raise last_exception


from hyperliquid_executor import HyperliquidExecutor, MockExecutor
from telegram_alerts import TelegramAlert, MockTelegramAlert
from logger import get_logger, setup_file_logging

# Initialize logger
logger = get_logger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG = {
    'check_interval_hours': 1,          # How often to check (for continuous mode)
    'rebalance_day': 6,                 # Day of week to rebalance (0=Mon, 6=Sun)
    'rebalance_hour': 12,               # Hour to rebalance (UTC)
    'position_tolerance': 0.10,         # 10% tolerance before rebalancing
    'heartbeat_interval_hours': 24,     # Send heartbeat every 24h
    'data_path': 'btc_data.csv',        # Local data file
    'state_file': 'bot_state.json',     # Persistent state file

    # Deployment diversification settings
    # Spreads execution across multiple days to reduce timing luck (+19.9% IRR improvement)
    'deployment_mode': 'diversified',   # 'single' or 'diversified'
    'signal_day': 6,                    # Sunday - compute signal once per week
    'signal_hour': 12,                  # Hour to compute signal (UTC)
    'deployment_days': [0, 1, 2, 3, 4, 5, 6],  # All days for 1/7th each
    'deployment_fraction': 1/7,         # Fraction of position change per day
    'deployment_hour': 12,              # Hour to execute daily portion (UTC)
}


# ============================================================================
# PERSISTENT STATE
# ============================================================================

def load_state() -> Dict[str, Any]:
    """Load bot state from disk for recovery after restart."""
    state_path = Path(CONFIG['state_file'])
    if state_path.exists():
        try:
            with open(state_path, 'r') as f:
                state = json.load(f)
                logger.info(f"Loaded state from {state_path}")
                return state
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load state: {e}")
    return {}


def save_state(state: Dict[str, Any]) -> bool:
    """Save bot state to disk for recovery."""
    state_path = Path(CONFIG['state_file'])
    try:
        # Add timestamp
        state['saved_at'] = datetime.now(timezone.utc).isoformat()
        with open(state_path, 'w') as f:
            json.dump(state, f, indent=2, default=str)
        logger.debug(f"Saved state to {state_path}")
        return True
    except IOError as e:
        logger.error(f"Failed to save state: {e}")
        return False


# ============================================================================
# DIVERSIFIED DEPLOYMENT
# ============================================================================

class DiversifiedExecutor:
    """
    Spreads position changes across multiple days to reduce timing luck.

    Example: Signal says move from 1x to 3x (delta = +2x)
    - Each day executes 2x * (1/7) = 0.286x
    - After 7 days, full position reached

    Based on Corey Hoffstein's research on rebalance timing luck.
    Backtested improvement: +19.9% IRR vs single-day execution.
    """

    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize diversified executor.

        Args:
            config: Configuration dict (uses global CONFIG if not provided)
        """
        self.config = config or CONFIG
        self.deployment_days = self.config.get('deployment_days', [0, 1, 2, 3, 4, 5, 6])
        self.deployment_fraction = self.config.get('deployment_fraction', 1/7)

        # Target state (set when weekly signal updates)
        self.target_leverage = None
        self.current_leverage = None
        self.signal_date = None

    def set_target(self, new_target: float, current: float, signal_date: str = None):
        """
        Called when weekly signal updates target leverage.

        Args:
            new_target: Target leverage from signal
            current: Current position leverage
            signal_date: Date of the signal
        """
        self.target_leverage = new_target
        self.current_leverage = current
        self.signal_date = signal_date or datetime.now(timezone.utc).strftime('%Y-%m-%d')
        logger.info(f"DiversifiedExecutor: Target set to {new_target}x from {current}x")

    def get_daily_execution(self, day_of_week: int, current_actual_leverage: float = None) -> Dict[str, Any]:
        """
        Determine what to execute today.

        Args:
            day_of_week: 0=Monday, 6=Sunday
            current_actual_leverage: Current actual leverage (from exchange)
                                     If provided, uses this instead of tracked value

        Returns:
            dict with:
                - action: 'none', 'skip', or 'execute'
                - leverage_change: Delta to apply
                - new_leverage: Target leverage after this execution
                - remaining_delta: How much left to reach final target
        """
        # Use actual leverage if provided (more accurate)
        if current_actual_leverage is not None:
            self.current_leverage = current_actual_leverage

        if self.target_leverage is None:
            return {
                'action': 'none',
                'leverage_change': 0,
                'new_leverage': self.current_leverage or 0,
                'remaining_delta': 0,
                'reason': 'No target set'
            }

        if day_of_week not in self.deployment_days:
            return {
                'action': 'skip',
                'leverage_change': 0,
                'new_leverage': self.current_leverage,
                'remaining_delta': self.target_leverage - self.current_leverage,
                'reason': f'Day {day_of_week} not in deployment days'
            }

        # Calculate today's portion
        total_delta = self.target_leverage - self.current_leverage

        if abs(total_delta) < 0.05:  # Close enough (5% of 1x)
            return {
                'action': 'none',
                'leverage_change': 0,
                'new_leverage': self.current_leverage,
                'remaining_delta': total_delta,
                'reason': 'Already at target (within tolerance)'
            }

        # Calculate daily move
        daily_delta = total_delta * self.deployment_fraction
        new_leverage = self.current_leverage + daily_delta

        # Ensure we don't overshoot
        if total_delta > 0:
            new_leverage = min(new_leverage, self.target_leverage)
        else:
            new_leverage = max(new_leverage, self.target_leverage)

        return {
            'action': 'execute',
            'leverage_change': daily_delta,
            'new_leverage': new_leverage,
            'remaining_delta': self.target_leverage - new_leverage,
            'reason': f'Daily portion: {daily_delta:+.3f}x'
        }

    def update_after_execution(self, actual_new_leverage: float):
        """Update tracked leverage after successful execution."""
        self.current_leverage = actual_new_leverage
        logger.debug(f"DiversifiedExecutor: Updated current leverage to {actual_new_leverage}x")

    def get_state(self) -> Dict[str, Any]:
        """Get serializable state for persistence."""
        return {
            'target_leverage': self.target_leverage,
            'current_leverage': self.current_leverage,
            'signal_date': self.signal_date,
        }

    def load_state(self, state: Dict[str, Any]):
        """Load state from persistence."""
        self.target_leverage = state.get('target_leverage')
        self.current_leverage = state.get('current_leverage')
        self.signal_date = state.get('signal_date')
        if self.target_leverage is not None:
            logger.info(f"DiversifiedExecutor: Restored state - target={self.target_leverage}x, current={self.current_leverage}x")


def is_signal_time() -> bool:
    """Check if current time is within signal generation window (Sunday)."""
    now = datetime.now(timezone.utc)

    # Check if it's signal day (Sunday by default)
    if now.weekday() != CONFIG.get('signal_day', 6):
        return False

    # Check if it's within signal hour
    target_hour = CONFIG.get('signal_hour', 12)
    if abs(now.hour - target_hour) > 1:
        return False

    return True


def is_deployment_time() -> bool:
    """Check if current time is within daily deployment window."""
    now = datetime.now(timezone.utc)

    # Check if today is a deployment day
    if now.weekday() not in CONFIG.get('deployment_days', [0, 1, 2, 3, 4, 5, 6]):
        return False

    # Check if it's within deployment hour
    target_hour = CONFIG.get('deployment_hour', 12)
    if abs(now.hour - target_hour) > 1:
        return False

    return True


# ============================================================================
# DATA FETCHING
# ============================================================================

def fetch_btc_data_hyperliquid(days: int = 365 * 5) -> Optional[str]:
    """
    Fetch BTC price data from Hyperliquid API.

    This eliminates oracle mismatch since we trade on Hyperliquid.
    Uses the same price feed the exchange uses for mark price.

    Args:
        days: Number of days of history (max ~5000 for daily candles)

    Returns:
        Path to saved CSV file, or None if failed
    """
    logger.info(f"Fetching {days} days of BTC data from Hyperliquid...")

    try:
        from hyperliquid.info import Info
        from hyperliquid.utils import constants
    except ImportError:
        logger.warning("hyperliquid-python-sdk not installed, skipping Hyperliquid data fetch")
        return None

    def do_fetch():
        info = Info(constants.MAINNET_API_URL, skip_ws=True)

        # Calculate time range (milliseconds)
        end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_time = end_time - (days * 24 * 60 * 60 * 1000)

        # Fetch daily candles
        candles = info.candles_snapshot(
            name="BTC",
            interval="1d",
            startTime=start_time,
            endTime=end_time
        )
        return candles

    try:
        candles = retry_with_backoff(
            do_fetch,
            max_retries=3,
            base_delay=2.0,
            exceptions=(ConnectionError, TimeoutError, OSError, Exception)
        )

        if not candles:
            logger.warning("No candle data returned from Hyperliquid")
            return None

        # Create CSV
        output_path = Path(CONFIG['data_path'])

        with open(output_path, 'w') as f:
            f.write("date,open,high,low,close,volume\n")

            for candle in candles:
                # Hyperliquid returns: t (timestamp), o, h, l, c, v
                timestamp = candle.get('t', candle.get('T', 0))
                date = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).strftime('%Y-%m-%d')

                o = candle.get('o', candle.get('open', 0))
                h = candle.get('h', candle.get('high', 0))
                l = candle.get('l', candle.get('low', 0))
                c = candle.get('c', candle.get('close', 0))
                v = candle.get('v', candle.get('volume', 0))

                f.write(f"{date},{o},{h},{l},{c},{v}\n")

        logger.info(f"Saved {len(candles)} days of Hyperliquid data to {output_path}")
        return str(output_path)

    except Exception as e:
        logger.warning(f"Failed to fetch Hyperliquid data: {e}")
        return None


def fetch_btc_data_coingecko(days: int = 365 * 5) -> Optional[str]:
    """
    Fetch BTC price data from CoinGecko API with retry logic.

    Args:
        days: Number of days of history (max 365*5 for free tier)

    Returns:
        Path to saved CSV file, or None if failed
    """
    print(f"Fetching {days} days of BTC data from CoinGecko...")

    url = f"https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days={days}&interval=daily"

    def do_fetch():
        request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib.request.urlopen(request, timeout=30)
        return json.loads(response.read().decode('utf-8'))

    try:
        # Retry on network errors
        data = retry_with_backoff(
            do_fetch,
            max_retries=3,
            base_delay=2.0,
            exceptions=(urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ConnectionError)
        )

        # Parse prices
        prices = data.get('prices', [])

        if not prices:
            print("ERROR: No price data returned")
            return None

        # Create CSV
        output_path = Path(CONFIG['data_path'])

        with open(output_path, 'w') as f:
            f.write("date,open,high,low,close,volume\n")

            for timestamp, price in prices:
                date = datetime.fromtimestamp(timestamp / 1000).strftime('%Y-%m-%d')
                # CoinGecko only gives close prices, so we use same for OHLC
                f.write(f"{date},{price},{price},{price},{price},0\n")

        print(f"Saved {len(prices)} days of data to {output_path}")
        return str(output_path)

    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ConnectionError) as e:
        print(f"ERROR fetching data after retries: {e}")
        return None
    except (json.JSONDecodeError, KeyError) as e:
        print(f"ERROR parsing CoinGecko response: {e}")
        return None


def ensure_data_available(data_path: Optional[str] = None) -> str:
    """
    Ensure BTC data is available, fetching if necessary.

    Priority order:
    1. Hyperliquid API (eliminates oracle mismatch)
    2. CoinGecko API (fallback)
    3. Local CSV file (stale data fallback)

    Args:
        data_path: Path to existing data file, or None to auto-fetch

    Returns:
        Path to data file
    """
    if data_path and Path(data_path).exists():
        # Check if data is fresh (updated today)
        mtime = datetime.fromtimestamp(Path(data_path).stat().st_mtime)
        if mtime.date() == datetime.now().date():
            logger.info(f"Using existing data: {data_path}")
            return data_path
        else:
            logger.info(f"Data is stale (last updated: {mtime.date()})")

    # Try Hyperliquid first (preferred - eliminates oracle mismatch)
    fetched_path = fetch_btc_data_hyperliquid()

    if fetched_path:
        logger.info("Using Hyperliquid price data (no oracle mismatch)")
        return fetched_path

    # Fall back to CoinGecko
    logger.info("Hyperliquid fetch failed, trying CoinGecko...")
    fetched_path = fetch_btc_data_coingecko()

    if fetched_path:
        return fetched_path
    elif data_path and Path(data_path).exists():
        logger.warning("Using stale local data as fallback")
        return data_path
    else:
        raise ValueError("No BTC data available and failed to fetch")


# ============================================================================
# POSITION MANAGEMENT
# ============================================================================

def should_rebalance(current_leverage: float,
                     target_leverage: float,
                     current_side: str,
                     target_side: str,
                     force: bool = False) -> bool:
    """
    Determine if we should rebalance position.

    Args:
        current_leverage: Current position leverage (0 if no position)
        target_leverage: Target leverage from signal
        current_side: Current position side ('long', 'short', or None)
        target_side: Target side from signal
        force: Force rebalance regardless of tolerance

    Returns:
        True if should rebalance
    """
    if force:
        return True

    # Always rebalance if going to/from cash
    if current_leverage == 0 and target_leverage > 0:
        return True
    if current_leverage > 0 and target_leverage == 0:
        return True

    # Always rebalance if side changes
    if current_side != target_side:
        return True

    # Check if leverage difference exceeds tolerance
    if current_leverage > 0:
        leverage_diff = abs(target_leverage - current_leverage) / current_leverage
        if leverage_diff > CONFIG['position_tolerance']:
            return True

    return False


def is_rebalance_time() -> bool:
    """Check if current time is within rebalance window"""
    now = datetime.now(timezone.utc)

    # Check if it's rebalance day
    if now.weekday() != CONFIG['rebalance_day']:
        return False

    # Check if it's within rebalance hour
    target_hour = CONFIG['rebalance_hour']
    if abs(now.hour - target_hour) > 1:
        return False

    return True


# ============================================================================
# MAIN BOT LOGIC
# ============================================================================

class TradingBot:
    """Main trading bot orchestrator"""

    def __init__(self,
                 executor=None,
                 alert=None,
                 data_path: Optional[str] = None,
                 dry_run: bool = False,
                 deployment_mode: str = None):
        """
        Initialize trading bot.

        Args:
            executor: HyperliquidExecutor or MockExecutor
            alert: TelegramAlert or MockTelegramAlert
            data_path: Path to BTC data CSV
            dry_run: If True, generate signals but don't execute
            deployment_mode: 'single' or 'diversified' (default from CONFIG)
        """
        self.executor = executor
        self.alert = alert
        self.data_path = data_path
        self.dry_run = dry_run
        self.deployment_mode = deployment_mode or CONFIG.get('deployment_mode', 'single')

        # Load persistent state for recovery
        saved_state = load_state()
        self.last_signal = saved_state.get('last_signal')
        self.last_execution = saved_state.get('last_execution')
        self.last_heartbeat = None
        self.last_signal_date = saved_state.get('last_signal_date')

        # Initialize diversified executor
        self.diversified_executor = DiversifiedExecutor(CONFIG)
        if 'diversified_state' in saved_state:
            self.diversified_executor.load_state(saved_state['diversified_state'])

        if saved_state.get('saved_at'):
            logger.info(f"Recovered state from {saved_state.get('saved_at')}")

        logger.info(f"TradingBot initialized (dry_run={dry_run}, deployment_mode={self.deployment_mode})")

    def run_once(self, force_rebalance: bool = False) -> Dict[str, Any]:
        """
        Run one iteration of the bot.

        In 'single' mode: generates signal and executes full position on rebalance day.
        In 'diversified' mode: generates signal on Sunday, executes 1/7th daily.

        Args:
            force_rebalance: Force rebalance regardless of time/tolerance

        Returns:
            Result dict with signal and execution info
        """
        if self.deployment_mode == 'diversified':
            return self._run_once_diversified(force_rebalance)
        else:
            return self._run_once_single(force_rebalance)

    def _run_once_single(self, force_rebalance: bool = False) -> Dict[str, Any]:
        """Single-day execution mode (original behavior)."""
        result = {
            'timestamp': datetime.now().isoformat(),
            'signal': None,
            'execution': None,
            'error': None,
            'mode': 'single',
        }

        try:
            # 1. Ensure data is available
            print("\n" + "=" * 60)
            print("STEP 1: Fetching data")
            print("=" * 60)
            data_path = ensure_data_available(self.data_path)

            # 2. Generate signal (with DVOL filter)
            print("\n" + "=" * 60)
            print("STEP 2: Generating signal")
            print("=" * 60)
            dvol_data = fetch_dvol_data()
            signal = generate_signal(data_path, dvol_data)

            if not signal:
                raise ValueError("Failed to generate signal")

            result['signal'] = signal
            self.last_signal = signal

            # Save state after signal generation
            save_state({'last_signal': signal, 'last_execution': self.last_execution})

            # Log signal
            logger.info(f"Signal: {signal['position']} @ {signal['leverage']}x")
            logger.info(f"Reasoning: {signal['reasoning']}")

            # 3. Send signal alert (with specialized alerts for danger/ATH)
            if self.alert:
                self.alert.send_signal(signal)

                # Immediate danger alert
                if signal.get('leverage') == 0 and signal.get('prob_left_tail', 0) > 0.20:
                    self.alert.send_danger_alert(signal)

                # ATH breakout alert
                if signal.get('ath_breakout') and signal.get('leverage') == 10:
                    self.alert.send_ath_breakout_alert(signal)

            # 4. Check if we should execute
            if self.dry_run:
                print("\n[DRY RUN] Skipping execution")
                result['execution'] = {'status': 'dry_run'}
                return result

            if not self.executor:
                print("\n[NO EXECUTOR] Skipping execution")
                result['execution'] = {'status': 'no_executor'}
                return result

            # 5. Get current position
            print("\n" + "=" * 60)
            print("STEP 3: Checking current position")
            print("=" * 60)

            current_pos = self.executor.get_btc_position()
            current_leverage = current_pos['leverage'] if current_pos else 0
            current_side = 'long' if current_pos and current_pos['size'] > 0 else 'short' if current_pos and current_pos['size'] < 0 else None

            print(f"Current: {current_leverage}x {current_side or 'none'}")
            print(f"Target: {signal['leverage']}x long")

            # 6. Determine if rebalancing needed
            target_side = 'long' if signal['leverage'] > 0 else None

            needs_rebalance = should_rebalance(
                current_leverage=current_leverage,
                target_leverage=signal['leverage'],
                current_side=current_side,
                target_side=target_side,
                force=force_rebalance,
            )

            if not needs_rebalance:
                print("\nNo rebalance needed (within tolerance)")
                result['execution'] = {'status': 'no_rebalance_needed'}
                return result

            # 7. Check if it's rebalance time (unless forced)
            if not force_rebalance and not is_rebalance_time():
                print(f"\nNot rebalance time (target: Sunday {CONFIG['rebalance_hour']}:00 UTC)")
                result['execution'] = {'status': 'not_rebalance_time'}
                return result

            # 8. Execute rebalance
            print("\n" + "=" * 60)
            print("STEP 4: Executing rebalance")
            print("=" * 60)

            execution = self.executor.set_position(
                leverage=signal['leverage'],
                side='long',
            )

            result['execution'] = execution
            self.last_execution = execution

            # Save state after execution
            save_state({'last_signal': self.last_signal, 'last_execution': execution})

            # 9. Send execution alert
            if self.alert:
                success = 'error' not in str(execution).lower()
                self.alert.send_execution_report(signal, execution, success)

            logger.info("Execution complete")
            return result

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error in run_once: {error_msg}", exc_info=True)
            result['error'] = error_msg

            if self.alert:
                self.alert.send_error(error_msg, "run_once")

            return result

    def _run_once_diversified(self, force_rebalance: bool = False) -> Dict[str, Any]:
        """
        Diversified deployment mode.

        - Signal generated on Sunday (signal_day)
        - Position change spread across all 7 days (1/7th each)
        - Reduces timing luck by ~50%
        """
        result = {
            'timestamp': datetime.now().isoformat(),
            'signal': None,
            'execution': None,
            'error': None,
            'mode': 'diversified',
        }

        now = datetime.now(timezone.utc)
        today_str = now.strftime('%Y-%m-%d')

        try:
            # 1. Check if we need to generate a new signal (Sunday, or forced)
            should_generate = force_rebalance or (is_signal_time() and self.last_signal_date != today_str)
            if should_generate:
                print("\n" + "=" * 60)
                print("SIGNAL DAY: Generating weekly signal")
                print("=" * 60)

                # Fetch data
                data_path = ensure_data_available(self.data_path)

                # Generate signal with DVOL filter
                dvol_data = fetch_dvol_data()
                signal = generate_signal(data_path, dvol_data)

                if not signal:
                    raise ValueError("Failed to generate signal")

                result['signal'] = signal
                self.last_signal = signal
                self.last_signal_date = today_str

                # Log signal
                logger.info(f"Weekly signal: {signal['position']} @ {signal['leverage']}x")
                logger.info(f"Reasoning: {signal['reasoning']}")

                # Send signal alert (with specialized alerts for danger/ATH)
                if self.alert:
                    self.alert.send_signal(signal)

                    if signal.get('leverage') == 0 and signal.get('prob_left_tail', 0) > 0.20:
                        self.alert.send_danger_alert(signal)

                    if signal.get('ath_breakout') and signal.get('leverage') == 10:
                        self.alert.send_ath_breakout_alert(signal)

                # Get current position to set up diversified executor
                if self.executor:
                    current_pos = self.executor.get_btc_position()
                    current_leverage = current_pos['leverage'] if current_pos else 0
                else:
                    current_leverage = 0

                # Set target for diversified execution
                self.diversified_executor.set_target(
                    new_target=signal['leverage'],
                    current=current_leverage,
                    signal_date=today_str
                )

                # Save state
                self._save_diversified_state()

            # 2. Check if we should execute today's portion
            if self.dry_run:
                print("\n[DRY RUN] Skipping execution")
                result['execution'] = {'status': 'dry_run'}
                return result

            if not self.executor:
                print("\n[NO EXECUTOR] Skipping execution")
                result['execution'] = {'status': 'no_executor'}
                return result

            if not force_rebalance and not is_deployment_time():
                print(f"\nNot deployment time (target: {CONFIG.get('deployment_hour', 12)}:00 UTC)")
                result['execution'] = {'status': 'not_deployment_time'}
                return result

            # Get current actual position
            current_pos = self.executor.get_btc_position()
            current_leverage = current_pos['leverage'] if current_pos else 0

            # Get today's execution plan
            execution_plan = self.diversified_executor.get_daily_execution(
                day_of_week=now.weekday(),
                current_actual_leverage=current_leverage
            )

            print("\n" + "=" * 60)
            print(f"DAILY EXECUTION (Day {now.weekday()}: {now.strftime('%A')})")
            print("=" * 60)
            print(f"Current leverage: {current_leverage}x")
            print(f"Target leverage: {self.diversified_executor.target_leverage}x")
            print(f"Action: {execution_plan['action']}")
            print(f"Reason: {execution_plan['reason']}")

            if execution_plan['action'] != 'execute':
                result['execution'] = {
                    'status': execution_plan['action'],
                    'reason': execution_plan['reason'],
                    'remaining_delta': execution_plan['remaining_delta']
                }
                return result

            # Execute today's portion
            print(f"\nExecuting: {execution_plan['leverage_change']:+.3f}x -> {execution_plan['new_leverage']:.3f}x")

            execution = self.executor.set_position(
                leverage=execution_plan['new_leverage'],
                side='long',
            )

            result['execution'] = {
                **execution,
                'daily_change': execution_plan['leverage_change'],
                'target_leverage': execution_plan['new_leverage'],
                'remaining_delta': execution_plan['remaining_delta'],
            }
            self.last_execution = result['execution']

            # Update diversified executor with actual result
            self.diversified_executor.update_after_execution(execution_plan['new_leverage'])

            # Save state
            self._save_diversified_state()

            # Send daily execution alert
            if self.alert:
                success = 'error' not in str(execution).lower()
                self.alert.send_daily_execution(
                    leverage_change=execution_plan['leverage_change'],
                    new_leverage=execution_plan['new_leverage'],
                    target_leverage=self.diversified_executor.target_leverage,
                    remaining_delta=execution_plan['remaining_delta'],
                    success=success
                )

            logger.info(f"Daily execution complete: {execution_plan['leverage_change']:+.3f}x")
            return result

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error in run_once_diversified: {error_msg}", exc_info=True)
            result['error'] = error_msg

            if self.alert:
                self.alert.send_error(error_msg, "run_once_diversified")

            return result

    def _save_diversified_state(self):
        """Save state including diversified executor state."""
        state = {
            'last_signal': self.last_signal,
            'last_execution': self.last_execution,
            'last_signal_date': self.last_signal_date,
            'diversified_state': self.diversified_executor.get_state(),
        }
        save_state(state)

    def run_continuous(self, check_interval_hours: Optional[float] = None):
        """
        Run continuously, checking at specified interval.

        Args:
            check_interval_hours: Hours between checks (default from config)
        """
        interval = check_interval_hours or CONFIG['check_interval_hours']
        interval_seconds = interval * 3600

        print(f"\nStarting continuous mode (checking every {interval}h)")
        print("Press Ctrl+C to stop\n")

        while True:
            try:
                # Run one iteration
                result = self.run_once()

                # Send heartbeat if needed
                if self.alert:
                    now = datetime.now()
                    if (not self.last_heartbeat or
                        (now - self.last_heartbeat).total_seconds() > CONFIG['heartbeat_interval_hours'] * 3600):

                        status = {
                            'last_signal_time': self.last_signal.get('date') if self.last_signal else 'N/A',
                            'current_position': self.last_signal.get('position') if self.last_signal else 'N/A',
                            'account_value': 0,
                        }

                        if self.executor:
                            try:
                                account = self.executor.get_account_info()
                                status['account_value'] = account.get('account_value', 0)
                            except (ConnectionError, TimeoutError, ValueError, KeyError) as e:
                                print(f"Warning: Failed to get account info for heartbeat: {e}")

                        self.alert.send_heartbeat(status)
                        self.last_heartbeat = now

                # Sleep until next check
                print(f"\nSleeping for {interval}h until next check...")
                time.sleep(interval_seconds)

            except KeyboardInterrupt:
                print("\n\nStopping bot...")
                break
            except Exception as e:
                print(f"\nERROR in main loop: {e}")
                if self.alert:
                    self.alert.send_error(str(e), "continuous_loop")
                time.sleep(60)  # Wait 1 minute before retrying


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='BTC Tail Model Trading Bot v10')

    # Mode
    parser.add_argument('--once', action='store_true',
                        help='Run once and exit')
    parser.add_argument('--continuous', action='store_true',
                        help='Run continuously')

    # Options
    parser.add_argument('--dry-run', action='store_true',
                        help='Generate signals but do not execute trades')
    parser.add_argument('--mock', action='store_true',
                        help='Use mock executor and alerts (for testing)')
    parser.add_argument('--force', action='store_true',
                        help='Force rebalance regardless of time/tolerance')
    parser.add_argument('--testnet', action='store_true',
                        help='Use Hyperliquid testnet')

    # Deployment mode
    parser.add_argument('--deployment', type=str, choices=['single', 'diversified'],
                        default=None,
                        help='Deployment mode: single (all at once) or diversified (spread over week)')

    # Data
    parser.add_argument('--data', type=str, default=None,
                        help='Path to BTC data CSV')

    # Intervals
    parser.add_argument('--interval', type=float, default=None,
                        help='Check interval in hours (for continuous mode)')

    args = parser.parse_args()

    # Default to --once if neither specified
    if not args.once and not args.continuous:
        args.once = True

    # Initialize components
    print("=" * 60)
    print("BTC TAIL MODEL TRADING BOT v10")
    print("=" * 60)
    print(f"Mode: {'continuous' if args.continuous else 'once'}")
    print(f"Deployment: {args.deployment or CONFIG.get('deployment_mode', 'single')}")
    print(f"Dry run: {args.dry_run}")
    print(f"Mock: {args.mock}")
    print()

    # Executor
    if args.mock:
        executor = MockExecutor()
    elif args.dry_run:
        executor = None
    else:
        try:
            executor = HyperliquidExecutor(testnet=args.testnet)
        except Exception as e:
            print(f"WARNING: Failed to initialize Hyperliquid: {e}")
            print("Continuing in dry-run mode")
            executor = None

    # Alerts
    if args.mock:
        alert = MockTelegramAlert()
    else:
        alert = TelegramAlert()

    # Create bot
    bot = TradingBot(
        executor=executor,
        alert=alert,
        data_path=args.data,
        dry_run=args.dry_run,
        deployment_mode=args.deployment,
    )

    # Run
    if args.continuous:
        bot.run_continuous(check_interval_hours=args.interval)
    else:
        result = bot.run_once(force_rebalance=args.force)

        print("\n" + "=" * 60)
        print("RESULT")
        print("=" * 60)
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
