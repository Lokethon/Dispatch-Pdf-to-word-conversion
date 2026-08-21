# Dispatch Bot — GST Invoice PDF → Dispatch Label Word File

A Discord bot that automatically converts GST invoice PDFs into dispatch label Word files.

## Features

- 📥 **Monitors** a specific Discord channel for PDF uploads
- 📄 **Extracts** Order ID, customer name, address, and phone from GST invoices
- 📝 **Generates** formatted dispatch label Word files (font size 14)
- 📤 **Sends** output Word files to a separate Discord channel
- 📦 **Bulk processing** — upload multiple PDFs at once, get one combined Word file
- 🏷️ **Smart naming** — single: `D15125.docx`, bulk: `D15100_to_D15125.docx`

## Setup

### 1. Create a Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application** → give it a name (e.g., "Dispatch Bot")
3. Go to **Bot** tab → click **Reset Token** → copy the token
4. Under **Privileged Gateway Intents**, enable:
   - ✅ **Message Content Intent**
5. Go to **OAuth2 → URL Generator**:
   - Scopes: `bot`
   - Bot Permissions: `Send Messages`, `Attach Files`, `Read Message History`
6. Open the generated URL and add the bot to your Discord server

### 2. Get Channel IDs

1. In Discord, go to **Settings → Advanced** → enable **Developer Mode**
2. Right-click on your **input channel** (where team uploads PDFs) → **Copy Channel ID**
3. Right-click on your **output channel** (where bot sends Word files) → **Copy Channel ID**

### 3. Configure Environment

```bash
# Copy the example env file
cp .env.example .env

# Edit .env with your values
nano .env
```

Fill in:
```
DISCORD_BOT_TOKEN=your_actual_bot_token
INPUT_CHANNEL_ID=123456789012345678
OUTPUT_CHANNEL_ID=987654321098765432
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

### 5. Run the Bot

```bash
python bot.py
```

You should see:
```
🚀 Starting Dispatch Bot...
✅ Bot is online as DispatchBot#1234
📥 Monitoring Input Channel ID: 123456789012345678
📤 Output Channel ID: 987654321098765432
```

## Usage

1. **Upload PDFs** to the input channel — drag & drop one or multiple GST invoice PDFs
2. The bot will **process** them and show a status message in the input channel
3. The **dispatch Word file** appears in the output channel

### Output Format

Each order in the Word file follows this format (font size 14):

```
Order Id: #D15125         ← Bold
To                        ← Bold
Sanvitha allam            ← Bold (customer name)
 5-4-99/A, Pakabanda...  ← Normal (address)
Khammam, Telangana - 507001  ← Normal (city, state - pin)
Ph: 8074880903            ← "Ph:" bold, number normal
```

### File Naming

| Scenario | Filename |
|---|---|
| Single PDF uploaded | `D15125.docx` |
| Multiple PDFs uploaded | `D15100_to_D15125.docx` |

## Troubleshooting

| Issue | Solution |
|---|---|
| Bot doesn't respond to PDFs | Check that `INPUT_CHANNEL_ID` is correct |
| "Output channel not found" | Check that `OUTPUT_CHANNEL_ID` is correct and bot has access |
| "Could not extract text from PDF" | The PDF might be image-based (scanned). This bot works with text-based PDFs |
| Bot is offline | Check your `DISCORD_BOT_TOKEN` is valid |

## Project Structure

```
Disptach/
├── bot.py               # Main Discord bot
├── pdf_parser.py         # GST PDF text extraction
├── word_generator.py     # Dispatch Word file generation
├── config.py             # Configuration loader
├── requirements.txt      # Python dependencies
├── .env                  # Your credentials (not committed)
├── .env.example          # Template for .env
└── README.md             # This file
```
