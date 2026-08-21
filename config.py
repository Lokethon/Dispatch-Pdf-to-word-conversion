import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Discord Bot Token
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Hardcoded Channel IDs
# INPUT_CHANNEL_ID  — The channel where team uploads GST invoice PDFs
# OUTPUT_CHANNEL_ID — The channel where the bot posts dispatch Word files
INPUT_CHANNEL_ID = int(os.getenv("INPUT_CHANNEL_ID", "0"))
OUTPUT_CHANNEL_ID = int(os.getenv("OUTPUT_CHANNEL_ID", "0"))

# Validation
if not DISCORD_BOT_TOKEN:
    raise ValueError("DISCORD_BOT_TOKEN is not set in .env file")
if INPUT_CHANNEL_ID == 0:
    raise ValueError("INPUT_CHANNEL_ID is not set in .env file")
if OUTPUT_CHANNEL_ID == 0:
    raise ValueError("OUTPUT_CHANNEL_ID is not set in .env file")
