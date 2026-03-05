"""
Hyperliquid Executor
====================
Connects to Hyperliquid API to execute BTC perpetual trades.

Setup:
    1. pip install hyperliquid-python-sdk
    2. Export your private key as environment variable:
       export HL_PRIVATE_KEY="your_private_key_here"
    3. Or create a .env file with HL_PRIVATE_KEY=your_key

Usage:
    from hyperliquid_executor import HyperliquidExecutor

    executor = HyperliquidExecutor()
    executor.set_position(leverage=3, side='long')
    executor.close_position()

IMPORTANT:
    - Test with small amounts first!
    - Use testnet for development
    - Never commit your private key
"""

import os
import json
import time
from decimal import Decimal
from typing import Optional, Dict, Any, Callable
from datetime import datetime


def retry_with_backoff(func: Callable, max_retries: int = 3, base_delay: float = 1.0,
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
                print(f"  API call failed: {e}. Retrying in {delay}s... (attempt {attempt + 1}/{max_retries + 1})")
                time.sleep(delay)
            else:
                print(f"  All {max_retries + 1} attempts failed")

    raise last_exception


# Network exceptions to retry on
RETRY_EXCEPTIONS = (ConnectionError, TimeoutError, OSError)

# Trading configuration
EXECUTOR_CONFIG = {
    'slippage_tolerance': 0.005,    # 0.5% default slippage for market orders
    'min_trade_size_btc': 0.0001,   # Minimum BTC trade size
    'max_leverage': 50,              # Maximum allowed leverage
    'min_leverage': 1,               # Minimum leverage
}

try:
    from hyperliquid.info import Info
    from hyperliquid.exchange import Exchange
    from hyperliquid.utils import constants
    HYPERLIQUID_AVAILABLE = True
except ImportError:
    HYPERLIQUID_AVAILABLE = False
    print("WARNING: hyperliquid-python-sdk not installed")
    print("Run: pip install hyperliquid-python-sdk")


class HyperliquidExecutor:
    """
    Execute trades on Hyperliquid for BTC perpetuals.
    """

    SYMBOL = "BTC"  # BTC perpetual on Hyperliquid

    def __init__(self, private_key: Optional[str] = None, testnet: bool = False):
        """
        Initialize Hyperliquid connection.

        Args:
            private_key: Your wallet private key. If None, reads from HL_PRIVATE_KEY env var
            testnet: If True, use testnet instead of mainnet
        """
        if not HYPERLIQUID_AVAILABLE:
            raise ImportError("hyperliquid-python-sdk not installed")

        # Get private key
        self.private_key = private_key or os.environ.get('HL_PRIVATE_KEY')
        if not self.private_key:
            raise ValueError(
                "Private key required. Set HL_PRIVATE_KEY environment variable "
                "or pass private_key parameter"
            )

        # Initialize API
        self.testnet = testnet
        base_url = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL

        self.info = Info(base_url, skip_ws=True)
        self.exchange = Exchange(self.private_key, base_url)

        # Get wallet address
        self.address = self.exchange.wallet.address

        print(f"Hyperliquid Executor initialized")
        print(f"  Network: {'TESTNET' if testnet else 'MAINNET'}")
        print(f"  Address: {self.address}")

    def get_account_info(self) -> Dict[str, Any]:
        """Get account balance and positions with retry logic"""
        user_state = retry_with_backoff(
            lambda: self.info.user_state(self.address),
            max_retries=3,
            base_delay=1.0,
            exceptions=RETRY_EXCEPTIONS
        )

        # Extract relevant info
        margin_summary = user_state.get('marginSummary', {})

        account_info = {
            'address': self.address,
            'account_value': float(margin_summary.get('accountValue', 0)),
            'total_margin_used': float(margin_summary.get('totalMarginUsed', 0)),
            'withdrawable': float(user_state.get('withdrawable', 0)),
            'positions': [],
        }

        # Get positions
        for pos in user_state.get('assetPositions', []):
            position = pos.get('position', {})
            if position:
                # Safely extract leverage - handle both dict and scalar formats
                leverage_data = position.get('leverage', 1)
                if isinstance(leverage_data, dict):
                    leverage_value = float(leverage_data.get('value', 1))
                else:
                    leverage_value = float(leverage_data) if leverage_data else 1.0

                account_info['positions'].append({
                    'symbol': position.get('coin'),
                    'size': float(position.get('szi', 0)),
                    'entry_price': float(position.get('entryPx', 0)),
                    'unrealized_pnl': float(position.get('unrealizedPnl', 0)),
                    'leverage': leverage_value,
                })

        return account_info

    def get_btc_position(self) -> Optional[Dict[str, Any]]:
        """Get current BTC position if any"""
        account = self.get_account_info()

        for pos in account['positions']:
            if pos['symbol'] == self.SYMBOL:
                return pos

        return None

    def get_btc_price(self) -> float:
        """Get current BTC mid price with retry logic"""
        all_mids = retry_with_backoff(
            lambda: self.info.all_mids(),
            max_retries=3,
            base_delay=1.0,
            exceptions=RETRY_EXCEPTIONS
        )
        return float(all_mids.get(self.SYMBOL, 0))

    def set_leverage(self, leverage: int) -> bool:
        """
        Set leverage for BTC perpetual.

        Args:
            leverage: Target leverage (1-50 on Hyperliquid)

        Returns:
            True if successful
        """
        # Clamp to valid range
        leverage = max(EXECUTOR_CONFIG['min_leverage'],
                      min(EXECUTOR_CONFIG['max_leverage'], leverage))

        try:
            result = retry_with_backoff(
                lambda: self.exchange.update_leverage(
                    leverage=leverage,
                    coin=self.SYMBOL,
                    is_cross=True  # Use cross margin
                ),
                max_retries=3,
                base_delay=1.0,
                exceptions=RETRY_EXCEPTIONS
            )
            print(f"Set leverage to {leverage}x: {result}")
            return True
        except RETRY_EXCEPTIONS as e:
            print(f"ERROR setting leverage after retries: {e}")
            return False
        except ValueError as e:
            print(f"ERROR setting leverage (invalid value): {e}")
            return False

    def market_order(self, size: float, side: str, reduce_only: bool = False) -> Dict[str, Any]:
        """
        Place a market order.

        Args:
            size: Position size in BTC
            side: 'buy' or 'sell'
            reduce_only: If True, only reduce existing position

        Returns:
            Order result
        """
        is_buy = side.lower() == 'buy'

        # Get current price for slippage calculation
        current_price = self.get_btc_price()

        # Use a limit order with aggressive price for "market" execution
        slippage = EXECUTOR_CONFIG['slippage_tolerance']
        if is_buy:
            limit_price = current_price * (1 + slippage)
        else:
            limit_price = current_price * (1 - slippage)

        order_result = retry_with_backoff(
            lambda: self.exchange.order(
                coin=self.SYMBOL,
                is_buy=is_buy,
                sz=size,
                limit_px=limit_price,
                order_type={"limit": {"tif": "Ioc"}},  # Immediate or cancel
                reduce_only=reduce_only,
            ),
            max_retries=3,
            base_delay=1.0,
            exceptions=RETRY_EXCEPTIONS
        )

        return order_result

    def close_position(self) -> Optional[Dict[str, Any]]:
        """Close entire BTC position"""
        position = self.get_btc_position()

        if not position or position['size'] == 0:
            print("No position to close")
            return None

        size = abs(position['size'])
        side = 'sell' if position['size'] > 0 else 'buy'

        print(f"Closing position: {position['size']} BTC")
        return self.market_order(size, side, reduce_only=True)

    def set_position(self,
                     leverage: int,
                     side: str = 'long',
                     account_fraction: float = 0.95) -> Dict[str, Any]:
        """
        Set position to target leverage and side.

        This will:
        1. Close any existing position if direction differs
        2. Set the leverage
        3. Open position using specified fraction of account

        Args:
            leverage: Target leverage (0 = close position)
            side: 'long' or 'short' (only 'long' used in our strategy)
            account_fraction: Fraction of account to use (default 95%)

        Returns:
            Execution result
        """
        result = {
            'timestamp': datetime.now().isoformat(),
            'target_leverage': leverage,
            'target_side': side,
            'actions': [],
        }

        # If leverage is 0, just close position
        if leverage == 0:
            close_result = self.close_position()
            result['actions'].append({'action': 'close', 'result': close_result})
            return result

        # Get current state
        account = self.get_account_info()
        current_position = self.get_btc_position()
        current_price = self.get_btc_price()

        account_value = account['account_value']

        # Calculate target position size
        # Position size = (Account Value * Leverage) / Price
        target_notional = account_value * leverage * account_fraction
        target_size = target_notional / current_price

        if side == 'short':
            target_size = -target_size

        # Determine current size
        current_size = current_position['size'] if current_position else 0

        # Calculate size delta
        size_delta = target_size - current_size

        print(f"Account value: ${account_value:,.2f}")
        print(f"BTC price: ${current_price:,.2f}")
        print(f"Current position: {current_size:.4f} BTC")
        print(f"Target position: {target_size:.4f} BTC ({leverage}x {side})")
        print(f"Size delta: {size_delta:.4f} BTC")

        # Set leverage first
        self.set_leverage(leverage)
        result['actions'].append({'action': 'set_leverage', 'leverage': leverage})

        # Execute trade if needed
        min_size = EXECUTOR_CONFIG['min_trade_size_btc']
        if abs(size_delta) > min_size:
            trade_side = 'buy' if size_delta > 0 else 'sell'
            trade_size = abs(size_delta)

            print(f"Executing: {trade_side} {trade_size:.4f} BTC")
            order_result = self.market_order(trade_size, trade_side)
            result['actions'].append({
                'action': 'market_order',
                'side': trade_side,
                'size': trade_size,
                'result': order_result,
            })
        else:
            print("Position already at target (within tolerance)")
            result['actions'].append({'action': 'no_change', 'reason': 'within_tolerance'})

        # Get final position
        final_position = self.get_btc_position()
        result['final_position'] = final_position

        return result


class MockExecutor:
    """
    Mock executor for testing without real trades.
    Same interface as HyperliquidExecutor but just logs actions.
    """

    def __init__(self):
        self.position = {'size': 0, 'leverage': 1, 'side': None}
        self.account_value = 10000  # Mock $10k account
        print("MockExecutor initialized (no real trades)")

    def get_account_info(self) -> Dict[str, Any]:
        return {
            'address': '0xMOCK',
            'account_value': self.account_value,
            'positions': [self.position] if self.position['size'] != 0 else [],
        }

    def get_btc_position(self) -> Optional[Dict[str, Any]]:
        if self.position['size'] != 0:
            return self.position
        return None

    def get_btc_price(self) -> float:
        return 95000.0  # Mock price

    def close_position(self):
        print(f"[MOCK] Closing position: {self.position}")
        self.position = {'size': 0, 'leverage': 1, 'side': None}
        return {'status': 'mock_closed'}

    def set_position(self, leverage: int, side: str = 'long', account_fraction: float = 0.95):
        print(f"[MOCK] Setting position: {leverage}x {side}")

        if leverage == 0:
            return self.close_position()

        price = self.get_btc_price()
        size = (self.account_value * leverage * account_fraction) / price
        if side == 'short':
            size = -size

        self.position = {
            'size': size,
            'leverage': leverage,
            'side': side,
            'entry_price': price,
        }

        print(f"[MOCK] New position: {self.position}")
        return {'status': 'mock_executed', 'position': self.position}


# ============================================================================
# TEST
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Hyperliquid Executor')
    parser.add_argument('--mock', action='store_true', help='Use mock executor')
    parser.add_argument('--testnet', action='store_true', help='Use testnet')
    parser.add_argument('--info', action='store_true', help='Show account info')
    parser.add_argument('--leverage', type=int, help='Set position leverage')
    parser.add_argument('--close', action='store_true', help='Close position')

    args = parser.parse_args()

    # Initialize executor
    if args.mock:
        executor = MockExecutor()
    else:
        executor = HyperliquidExecutor(testnet=args.testnet)

    # Execute command
    if args.info:
        info = executor.get_account_info()
        print(json.dumps(info, indent=2))

    elif args.close:
        result = executor.close_position()
        print(json.dumps(result, indent=2))

    elif args.leverage is not None:
        result = executor.set_position(leverage=args.leverage, side='long')
        print(json.dumps(result, indent=2, default=str))

    else:
        # Default: show account info
        info = executor.get_account_info()
        print("\nAccount Info:")
        print(f"  Value: ${info['account_value']:,.2f}")
        print(f"  Positions: {len(info['positions'])}")

        pos = executor.get_btc_position()
        if pos:
            print(f"\nBTC Position:")
            print(f"  Size: {pos['size']:.4f} BTC")
            print(f"  Leverage: {pos.get('leverage', 'N/A')}x")
