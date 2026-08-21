"""
bot.py — Discord Bot for GST Invoice PDF → Dispatch Label Word File automation.

Monitors a specific input Discord channel for PDF uploads.
Extracts Ship To details and Order ID from each GST invoice PDF.
Generates dispatch label Word files and posts them to an output channel.

Features:
    - Animated loading messages during processing
    - Multi-page PDF support (each page = separate invoice)
    - Bulk PDF support (multiple files at once)

Usage:
    1. Configure .env with your bot token and channel IDs
    2. pip install -r requirements.txt
    3. python bot.py
"""

import os
import sys
import tempfile
import shutil
import logging
import asyncio

import discord
from discord.ext import commands

from config import DISCORD_BOT_TOKEN, INPUT_CHANNEL_ID, OUTPUT_CHANNEL_ID
from pdf_parser import extract_all_orders
from word_generator import generate_dispatch_word

# ─── Logging Setup ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("DispatchBot")

# ─── Bot Setup ───────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True  # Required to read message attachments

bot = commands.Bot(command_prefix="!", intents=intents)

# ─── Loading Animation Frames ────────────────────────────────────────────────
LOADING_FRAMES = [
    "⏳ Processing",
    "⏳ Processing.",
    "⏳ Processing..",
    "⏳ Processing...",
]


@bot.event
async def on_ready():
    """Called when the bot is ready and connected to Discord."""
    logger.info(f"✅ Bot is online as {bot.user}")
    logger.info(f"📥 Monitoring Input Channel ID:  {INPUT_CHANNEL_ID}")
    logger.info(f"📤 Output Channel ID:            {OUTPUT_CHANNEL_ID}")

    # Verify channels exist
    input_ch = bot.get_channel(INPUT_CHANNEL_ID)
    output_ch = bot.get_channel(OUTPUT_CHANNEL_ID)

    if input_ch is None:
        logger.warning(
            f"⚠️  Could not find input channel {INPUT_CHANNEL_ID}. "
            "Make sure the bot has access to this channel."
        )
    else:
        logger.info(f"📥 Input Channel:  #{input_ch.name}")

    if output_ch is None:
        logger.warning(
            f"⚠️  Could not find output channel {OUTPUT_CHANNEL_ID}. "
            "Make sure the bot has access to this channel."
        )
    else:
        logger.info(f"📤 Output Channel: #{output_ch.name}")


@bot.event
async def on_message(message: discord.Message):
    """Handle incoming messages — process PDFs from the input channel only."""
    # Ignore bot's own messages
    if message.author == bot.user:
        return

    # Only process messages from the designated input channel
    if message.channel.id != INPUT_CHANNEL_ID:
        return

    # Check if the message has any PDF attachments
    pdf_attachments = [
        att for att in message.attachments
        if att.filename.lower().endswith(".pdf")
    ]

    if not pdf_attachments:
        return  # No PDFs, ignore

    logger.info(
        f"📎 Received {len(pdf_attachments)} PDF(s) from "
        f"{message.author.display_name} in #{message.channel.name}"
    )

    # ─── Send animated loading message ────────────────────────────────
    loading_embed = discord.Embed(
        title="📄 Processing PDF",
        description=(
            f"```\n"
            f"📥 Received {len(pdf_attachments)} PDF file(s)\n"
            f"⏳ Downloading & reading...\n"
            f"```"
        ),
        color=0xFFA500,  # Orange
    )
    loading_embed.set_footer(text="Please wait while I extract the dispatch details...")
    loading_msg = await message.channel.send(embed=loading_embed)

    # Start the loading animation in the background
    animation_running = asyncio.Event()
    animation_running.set()
    animation_task = asyncio.create_task(
        _animate_loading(loading_msg, animation_running, pdf_attachments)
    )

    # Create a temporary directory for processing
    temp_dir = tempfile.mkdtemp(prefix="dispatch_")

    try:
        # Step 1: Download all PDFs
        pdf_paths = []
        for att in pdf_attachments:
            pdf_path = os.path.join(temp_dir, att.filename)
            await att.save(pdf_path)
            pdf_paths.append(pdf_path)
            logger.info(f"   ⬇️  Downloaded: {att.filename}")

        # Update loading message — downloading complete
        await _update_loading(
            loading_msg, pdf_attachments,
            stage="🔍 Scanning pages & extracting data...",
            color=0x3498DB,  # Blue
        )

        # Step 2: Parse each PDF and extract order data (page by page)
        all_orders = []
        errors = []

        for pdf_path in pdf_paths:
            filename = os.path.basename(pdf_path)
            try:
                orders = extract_all_orders(pdf_path)
                if orders:
                    all_orders.extend(orders)
                    logger.info(
                        f"   ✅ {filename}: extracted {len(orders)} order(s)"
                    )
                else:
                    errors.append(f"❌ `{filename}`: No orders found")
            except Exception as e:
                error_msg = f"❌ `{filename}`: {str(e)}"
                errors.append(error_msg)
                logger.error(f"   {error_msg}")

        # Deduplicate orders by order_id to prevent duplicates in the document
        unique_orders = []
        seen_ids = set()
        for order in all_orders:
            if order["order_id"] not in seen_ids:
                unique_orders.append(order)
                seen_ids.add(order["order_id"])
        all_orders = unique_orders

        # Stop the loading animation
        animation_running.clear()
        await animation_task

        if not all_orders:
            # All PDFs failed
            fail_embed = discord.Embed(
                title="❌ Processing Failed",
                description=(
                    f"Could not extract any orders from "
                    f"{len(pdf_attachments)} PDF(s).\n\n"
                    + "\n".join(errors)
                ),
                color=0xE74C3C,  # Red
            )
            await loading_msg.edit(embed=fail_embed)
            return

        # Update loading message — generating Word file
        await _update_loading(
            loading_msg, pdf_attachments,
            stage=f"📝 Generating dispatch file for {len(all_orders)} order(s)...",
            color=0x9B59B6,  # Purple
        )

        # Step 3: Generate Word document
        output_dir = os.path.join(temp_dir, "output")
        docx_path = generate_dispatch_word(all_orders, output_dir)
        docx_filename = os.path.basename(docx_path)
        logger.info(f"   📝 Generated Word file: {docx_filename}")

        # Step 4: Send Word file to the OUTPUT channel
        output_channel = bot.get_channel(OUTPUT_CHANNEL_ID)
        if output_channel is None:
            error_embed = discord.Embed(
                title="❌ Configuration Error",
                description="Output channel not found. Check OUTPUT_CHANNEL_ID.",
                color=0xE74C3C,
            )
            await loading_msg.edit(embed=error_embed)
            return

        # Build summary of processed orders
        order_ids = [f"#D{o['order_id']}" for o in all_orders]
        if len(all_orders) == 1:
            summary = f"📦 Dispatch label for order **{order_ids[0]}**"
        else:
            summary = (
                f"📦 Dispatch labels for **{len(all_orders)}** orders:\n"
                f"{', '.join(order_ids)}"
            )

        # Send to output channel
        await output_channel.send(
            content=summary,
            file=discord.File(docx_path, filename=docx_filename),
        )
        logger.info(f"   📤 Sent {docx_filename} to output channel")

        # Step 5: Update loading message to success in input channel
        success_embed = discord.Embed(
            title="✅ Dispatch Labels Ready!",
            description=(
                f"```\n"
                f"📄 Files processed : {len(pdf_attachments)}\n"
                f"📦 Orders extracted: {len(all_orders)}\n"
                f"📝 Output file     : {docx_filename}\n"
                f"```\n"
                f"**Orders:** {', '.join(order_ids)}\n\n"
                f"✅ Word file sent to output channel."
            ),
            color=0x2ECC71,  # Green
        )
        if errors:
            error_text = "\n".join(errors)
            success_embed.add_field(
                name="⚠️ Warnings",
                value=error_text[:1024],
                inline=False,
            )
        await loading_msg.edit(embed=success_embed)

    except Exception as e:
        # Stop animation on error
        animation_running.clear()
        try:
            await animation_task
        except Exception:
            pass

        logger.exception(f"Unexpected error processing PDFs: {e}")
        error_embed = discord.Embed(
            title="❌ Unexpected Error",
            description=f"```\n{str(e)}\n```",
            color=0xE74C3C,
        )
        await loading_msg.edit(embed=error_embed)

    finally:
        # Clean up temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)

    # Process other bot commands if any
    await bot.process_commands(message)


async def _animate_loading(
    msg: discord.Message,
    running: asyncio.Event,
    attachments: list,
):
    """
    Animate the loading message with cycling dots and spinner.
    Runs in the background until `running` is cleared.
    """
    frames = [
        ("⏳", "Processing"),
        ("⌛", "Processing."),
        ("⏳", "Processing.."),
        ("⌛", "Processing..."),
    ]
    frame_idx = 0

    while running.is_set():
        await asyncio.sleep(1.5)  # Update every 1.5 seconds
        if not running.is_set():
            break

        icon, text = frames[frame_idx % len(frames)]
        frame_idx += 1

        try:
            embed = discord.Embed(
                title=f"{icon} {text}",
                description=(
                    f"```\n"
                    f"📥 PDF files received: {len(attachments)}\n"
                    f"🔄 Reading & extracting data...\n"
                    f"```"
                ),
                color=0xFFA500,
            )
            embed.set_footer(
                text="Please wait while I extract the dispatch details..."
            )
            await msg.edit(embed=embed)
        except Exception:
            break  # Message was deleted or bot lost access


async def _update_loading(
    msg: discord.Message,
    attachments: list,
    stage: str,
    color: int,
):
    """Update the loading message with a new stage."""
    try:
        embed = discord.Embed(
            title="📄 Processing PDF",
            description=(
                f"```\n"
                f"📥 PDF files received: {len(attachments)}\n"
                f"{stage}\n"
                f"```"
            ),
            color=color,
        )
        embed.set_footer(
            text="Please wait while I extract the dispatch details..."
        )
        await msg.edit(embed=embed)
    except Exception:
        pass


# ─── Entry Point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("🚀 Starting Dispatch Bot...")
    bot.run(DISCORD_BOT_TOKEN)
