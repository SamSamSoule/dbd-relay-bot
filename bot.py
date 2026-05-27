"""
Discord Relay Bot
Relays messages from source channels to target servers via webhooks.
Configure relays in config.json.
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import discord
import aiohttp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        log.error("config.json not found.")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        return json.load(f)


class RelayBot(discord.Client):
    def __init__(self, config: dict):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.relay_map: dict[int, dict] = {}
        for relay in config.get("relays", []):
            channel_id = int(relay["source_channel_id"])
            webhooks = relay["target_webhooks"]
            if isinstance(webhooks, str):
                webhooks = [webhooks]
            self.relay_map[channel_id] = {
                "webhooks": webhooks,
                "ping_role_id": relay.get("ping_role_id"),
            }
            log.info("Relay configured: channel %s -> %d webhook(s)", channel_id, len(webhooks))

    async def on_ready(self):
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        log.info("Watching %d channel(s)", len(self.relay_map))

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        relay = self.relay_map.get(message.channel.id)
        if not relay:
            return
        log.info("Relaying message from %s in #%s (%s)", message.author, message.channel, message.guild)
        async with aiohttp.ClientSession() as session:
            for webhook_url in relay["webhooks"]:
                await self._send_to_webhook(session, webhook_url, message, relay.get("ping_role_id"))

    async def _send_to_webhook(self, session, webhook_url, message, ping_role_id=None):
        payload: dict = {
            "username": "Relay Bot",
            "avatar_url": str(self.user.display_avatar.url) if self.user else discord.utils.MISSING,
        }
        if ping_role_id:
            payload["content"] = f"<@&{ping_role_id}>"
        description_parts = []
        if message.content:
            description_parts.append(message.content)
        if message.stickers:
            description_parts.append(" ".join(f"[Sticker: {s.name}]" for s in message.stickers))
        main_embed: dict = {
            "color": 0x5865F2,
            "author": {
                "name": f"{message.author.display_name}",
                "icon_url": str(message.author.display_avatar.url),
            },
            "footer": {
                "text": f"#{message.channel.name}  ·  {message.guild.name}",
                "icon_url": str(message.guild.icon.url) if message.guild.icon else None,
            },
            "timestamp": message.created_at.isoformat(),
        }
        if description_parts:
            main_embed["description"] = "\n".join(description_parts)
        image_set = False
        extra_attachments = []
        for attachment in message.attachments:
            if not image_set and attachment.content_type and attachment.content_type.startswith("image/"):
                main_embed["image"] = {"url": attachment.url}
                image_set = True
            else:
                extra_attachments.append(attachment)
        embeds = [main_embed]
        if extra_attachments:
            embeds.append({
                "color": 0x5865F2,
                "description": "\n".join(f"📎 [{a.filename}]({a.url})" for a in extra_attachments),
            })
        if message.embeds:
            embeds.extend(e.to_dict() for e in message.embeds[:9])
        payload["embeds"] = embeds[:10]
        try:
            async with session.post(webhook_url, json=payload, params={"wait": "true"}) as resp:
                if resp.status not in (200, 204):
                    body = await resp.text()
                    log.error("Webhook returned %s: %s", resp.status, body)
        except aiohttp.ClientError as exc:
            log.error("Failed to send to webhook: %s", exc)


def main():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        log.error("DISCORD_BOT_TOKEN environment variable is not set.")
        sys.exit(1)
    config = load_config()
    bot = RelayBot(config)
    try:
        bot.run(token, log_handler=None)
    except discord.LoginFailure:
        log.error("Invalid bot token. Check DISCORD_BOT_TOKEN.")
        sys.exit(1)
    except discord.PrivilegedIntentsRequired:
        log.error("\n\n  ❌  Message Content Intent is not enabled!\n"
                  "  Go to https://discord.com/developers/applications/\n"
                  "  → Select your app → Bot → Privileged Gateway Intents\n"
                  "  → Enable 'Message Content Intent' → Save Changes\n"
                  "  Then restart the bot.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
