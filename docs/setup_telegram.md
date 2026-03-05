# Telegram Bot Setup Guide

## Step 1: Create Bot with BotFather

1. Open Telegram and search for @BotFather
2. Send `/newbot`
3. Follow prompts to name your bot
4. Save the bot token (looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

## Step 2: Get Your Chat ID

1. Search for @userinfobot on Telegram
2. Send any message
3. It will reply with your chat ID (a number like `123456789`)

## Step 3: Configure GitHub Secrets

Go to your repo Settings > Secrets and variables > Actions, and add:

- `TELEGRAM_BOT_TOKEN` - Your bot token from Step 1
- `TELEGRAM_CHAT_ID` - Your chat ID from Step 2
- `HL_PRIVATE_KEY` - Your Hyperliquid wallet private key

## Step 4: Local Testing

```bash
# Set env vars
export TELEGRAM_BOT_TOKEN="your_token_here"
export TELEGRAM_CHAT_ID="your_chat_id_here"

# Test in mock mode (no real messages)
python tests/test_telegram.py

# Send a real test message
python tests/test_telegram.py --live

# Or use the CLI
python src/telegram_alerts.py --test
```

## Step 5: Verify

You should receive a test message in your Telegram chat.

## Troubleshooting

### "Chat not found" error
- Make sure you've messaged the bot first (send /start)
- Verify your chat ID is correct

### "Unauthorized" error
- Check your bot token is correct
- Make sure there are no extra spaces

### No message received
- Check bot is not blocked
- Verify chat ID matches your user ID (not a group)
