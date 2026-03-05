"""
Test script for Telegram alerts
================================
Run with: python tests/test_telegram.py
Live test: python tests/test_telegram.py --live
"""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from telegram_alerts import TelegramAlert, MockTelegramAlert


# Sample signal data for tests
SAMPLE_SIGNAL = {
    'date': '2026-03-05',
    'price': 92861.02,
    'drawdown': -0.256,
    'prob_left_tail': 0.023,
    'near_ath': False,
    'ath_breakout': False,
    'vol_high': False,
    'leverage': 2,
    'position': '2x LONG',
    'reasoning': 'DD tier -60% to -70%, above EMA, MVRV boost',
    'ema_200': 45000,
    'above_ema_200': True,
    'mvrv': 2.5,
    'mvrv_boost_eligible': True,
    'dvol_zscore': 0.15,
    'dvol_filter_applied': False,
    'base_leverage': 2,
}

DANGER_SIGNAL = {
    'date': '2026-03-05',
    'price': 85000.00,
    'drawdown': -0.45,
    'prob_left_tail': 0.35,
    'leverage': 0,
    'position': 'CASH',
    'reasoning': 'Danger: XGBoost prob 35.0% > 20% threshold',
}

ATH_SIGNAL = {
    'date': '2026-03-05',
    'price': 110000.00,
    'drawdown': 0.0,
    'prob_left_tail': 0.02,
    'near_ath': True,
    'ath_breakout': True,
    'leverage': 10,
    'position': '10x LEVER',
    'reasoning': 'ATH breakout after >60% drawdown recovery',
}


def test_mock_mode():
    """Test that mock mode doesn't send real messages."""
    alert = MockTelegramAlert()
    assert alert.enabled is True

    result = alert.send_message("test message")
    assert result is True

    result = alert.send_signal(SAMPLE_SIGNAL)
    assert result is True

    result = alert.send_danger_alert(DANGER_SIGNAL)
    assert result is True

    result = alert.send_ath_breakout_alert(ATH_SIGNAL)
    assert result is True

    result = alert.send_error("test error", "test context")
    assert result is True

    result = alert.send_heartbeat({'last_signal_time': 'N/A', 'current_position': 'N/A', 'account_value': 10000})
    assert result is True

    result = alert.send_daily_execution(0.286, 1.286, 2.0, 0.714, True)
    assert result is True

    result = alert.send_status({'price': 92000, 'position': '2x LONG', 'leverage': 2, 'drawdown': -0.25, 'account_value': 10000, 'danger_prob': 0.02})
    assert result is True

    assert len(alert.messages) == 8
    print("  test_mock_mode... OK")


def test_message_formatting():
    """Test that messages format correctly with HTML."""
    alert = MockTelegramAlert()

    # Signal should not crash with missing fields
    minimal_signal = {'leverage': 1, 'position': '1x LONG'}
    result = alert.send_signal(minimal_signal)
    assert result is True

    # Full signal should work
    result = alert.send_signal(SAMPLE_SIGNAL)
    assert result is True

    print("  test_message_formatting... OK")


def test_send_weekly_signal():
    """Test weekly signal formatting with real TelegramAlert in disabled mode."""
    alert = TelegramAlert(bot_token=None, chat_id=None)
    assert alert.enabled is False

    # Should return False (disabled) but not crash
    result = alert.send_signal(SAMPLE_SIGNAL)
    assert result is False

    print("  test_send_weekly_signal... OK")


def test_send_danger_alert():
    """Test danger alert formatting."""
    alert = MockTelegramAlert()

    result = alert.send_danger_alert(DANGER_SIGNAL)
    assert result is True
    assert len(alert.messages) == 1
    assert alert.messages[0]['label'] == 'danger'

    print("  test_send_danger_alert... OK")


def test_send_ath_breakout():
    """Test ATH breakout alert."""
    alert = MockTelegramAlert()

    result = alert.send_ath_breakout_alert(ATH_SIGNAL)
    assert result is True
    assert alert.messages[0]['label'] == 'ath_breakout'

    print("  test_send_ath_breakout... OK")


def test_send_daily_execution():
    """Test daily execution update."""
    alert = MockTelegramAlert()

    result = alert.send_daily_execution(
        leverage_change=0.286,
        new_leverage=1.286,
        target_leverage=2.0,
        remaining_delta=0.714,
        success=True
    )
    assert result is True

    # Test failed execution
    result = alert.send_daily_execution(
        leverage_change=0.0,
        new_leverage=1.0,
        target_leverage=2.0,
        remaining_delta=1.0,
        success=False
    )
    assert result is True

    print("  test_send_daily_execution... OK")


def test_env_validation():
    """Test that missing env vars disable alerts gracefully."""
    # Save and clear env vars
    saved_token = os.environ.pop('TELEGRAM_BOT_TOKEN', None)
    saved_chat = os.environ.pop('TELEGRAM_CHAT_ID', None)

    try:
        alert = TelegramAlert()
        assert alert.enabled is False

        # Should return False but not crash
        result = alert.send_message("test")
        assert result is False
    finally:
        # Restore env vars
        if saved_token:
            os.environ['TELEGRAM_BOT_TOKEN'] = saved_token
        if saved_chat:
            os.environ['TELEGRAM_CHAT_ID'] = saved_chat

    print("  test_env_validation... OK")


def test_real_alert_object():
    """Test TelegramAlert with actual formatting (no send)."""
    # Create alert with fake credentials - it will be enabled but send will fail
    # We just verify it doesn't crash during message construction
    alert = TelegramAlert(bot_token=None, chat_id=None)

    # All methods should handle gracefully when disabled
    alert.send_signal(SAMPLE_SIGNAL)
    alert.send_danger_alert(DANGER_SIGNAL)
    alert.send_ath_breakout_alert(ATH_SIGNAL)
    alert.send_execution_report(SAMPLE_SIGNAL, {'status': 'ok'}, True)
    alert.send_error("test", "ctx")
    alert.send_heartbeat({'account_value': 0})
    alert.send_daily_execution(0.5, 1.5, 2.0, 0.5, True)
    alert.send_status({'price': 90000, 'position': 'LONG', 'leverage': 2, 'drawdown': -0.1, 'account_value': 10000, 'danger_prob': 0.01})

    print("  test_real_alert_object... OK")


def send_test_message():
    """Actually send a test message (requires env vars set)."""
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')

    if not token or not chat_id:
        print("ERROR: Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to run live test")
        sys.exit(1)

    alert = TelegramAlert()

    print("Sending test signal...")
    success = alert.send_signal(SAMPLE_SIGNAL)
    print(f"  Signal: {'OK' if success else 'FAILED'}")

    print("Sending test danger alert...")
    success = alert.send_danger_alert(DANGER_SIGNAL)
    print(f"  Danger: {'OK' if success else 'FAILED'}")

    print("Sending test ATH breakout...")
    success = alert.send_ath_breakout_alert(ATH_SIGNAL)
    print(f"  ATH Breakout: {'OK' if success else 'FAILED'}")

    print("Sending test heartbeat...")
    success = alert.send_heartbeat({
        'last_signal_time': '2026-03-05',
        'current_position': '2x LONG',
        'account_value': 10000.00,
    })
    print(f"  Heartbeat: {'OK' if success else 'FAILED'}")


def run_all_tests():
    print("Running Telegram alert tests...\n")

    test_mock_mode()
    test_message_formatting()
    test_send_weekly_signal()
    test_send_danger_alert()
    test_send_ath_breakout()
    test_send_daily_execution()
    test_env_validation()
    test_real_alert_object()

    print("\nAll tests passed!")


if __name__ == '__main__':
    if '--live' in sys.argv:
        send_test_message()
    else:
        run_all_tests()
