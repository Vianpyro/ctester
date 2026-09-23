import json
import sys
import threading
import urllib.request

import config
from services.forum import is_chat


def enabled():
    return bool(config.DISCORD_WEBHOOK)


def from_discord(account):
    return str(account or "").startswith(config.DISCORD_ACCOUNT_PREFIX)


def payload(author, text, channel):
    name = str(author or "Participant")
    if channel:
        name = name + " — " + str(channel)
    return {
        "username": name[:80],
        "content": str(text or "")[:1900],
        # Otherwise a message typed on the site could ping @everyone on the server.
        "allowed_mentions": {"parse": []},
    }


def _post(body):
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        config.DISCORD_WEBHOOK, data=data,
        headers={"Content-Type": "application/json"})
    # Discord being down must never fail the student's post.
    try:
        urllib.request.urlopen(request, timeout=config.DISCORD_TIMEOUT).close()
    except Exception as error:
        print("discord: webhook failed:", error, file=sys.stderr)


def announce(thread, account, author, text, channel=""):
    if not enabled():
        return False
    if not is_chat(thread):
        return False
    if from_discord(account):
        return False
    if not str(text or "").strip():
        return False
    body = payload(author, text, channel)
    # A slow or unavailable webhook must never delay a forum post.
    threading.Thread(target=_post, args=(body,), daemon=True).start()
    return True
