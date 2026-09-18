#!/usr/bin/env python3
"""Relays public Discord messages into the site's chat. Standard library only."""

import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://discord.com/api/v10"

TOKEN = os.environ.get("CTESTER_DISCORD_TOKEN", "").strip()
BRIDGE_URL = os.environ.get("CTESTER_BRIDGE_URL", "").strip().rstrip("/")
BRIDGE_KEY = os.environ.get("CTESTER_DISCORD_BRIDGE_KEY", "").strip()
STATE_PATH = os.environ.get("CTESTER_BRIDGE_STATE", "/state/bridge.json")
INTERVAL = int(os.environ.get("CTESTER_BRIDGE_INTERVAL", "5") or 5)


def parse_channels(raw):
    pairs = {}
    for piece in str(raw or "").replace("\n", ",").split(","):
        piece = piece.strip()
        if not piece or "=" not in piece:
            continue
        channel, thread = piece.split("=", 1)
        channel, thread = channel.strip(), thread.strip()
        # Only public chat threads: the bridge must never reach private questions.
        if channel.isdigit() and thread.startswith("@chat:"):
            pairs[channel] = thread
    return pairs


CHANNELS = parse_channels(os.environ.get("CTESTER_DISCORD_CHANNELS", ""))


def should_relay(message):
    if not isinstance(message, dict):
        return False
    # Messages posted by the site's own webhook would loop back.
    if message.get("webhook_id"):
        return False
    auteur = message.get("author") or {}
    if auteur.get("bot"):
        return False
    return bool(str(message.get("content") or "").strip())


def display_name(message):
    auteur = message.get("author") or {}
    member = message.get("member") or {}
    return (member.get("nick") or auteur.get("global_name")
            or auteur.get("username") or "Discord")


def read_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            value = json.load(fh)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def write_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_PATH) or ".", exist_ok=True)
        temporary = STATE_PATH + ".tmp"
        with open(temporary, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        os.replace(temporary, STATE_PATH)
    except Exception as error:
        print("ctester-bridge: state not written:", error, flush=True)


def _get(url):
    request = urllib.request.Request(
        url, headers={"Authorization": "Bot " + TOKEN,
                      "User-Agent": "ctester-bridge/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read(1 << 20))


def messages(channel, after):
    path = API + "/channels/" + channel + "/messages?limit=50"
    if after:
        path += "&after=" + after
    value = _get(path)
    return list(reversed(value)) if isinstance(value, list) else []


def push(thread, message):
    body = json.dumps({
        "exercise_id": thread,
        "discord_id": str((message.get("author") or {}).get("id") or ""),
        "display_name": display_name(message),
        "text": message.get("content") or "",
    }).encode("utf-8")
    request = urllib.request.Request(
        BRIDGE_URL + "/forum/bridge", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + BRIDGE_KEY})
    try:
        with urllib.request.urlopen(request, timeout=15):
            return True
    except urllib.error.HTTPError as error:
        print("ctester-bridge: refused (%s): %s"
              % (error.code, error.read(400)), flush=True)
        return False
    except Exception as error:
        print("ctester-bridge: API unreachable:", error, flush=True)
        return False


def poll_once(state):
    for channel, thread in CHANNELS.items():
        try:
            batch = messages(channel, state.get(channel))
        except Exception as error:
            print("ctester-bridge: Discord unreachable:", error, flush=True)
            continue
        # The position moves even past a refused message, or it would be retried forever.
        for message in batch:
            state[channel] = str(message.get("id") or state.get(channel) or "")
            if should_relay(message):
                push(thread, message)
    return state


def start():
    if not (TOKEN and BRIDGE_URL and BRIDGE_KEY and CHANNELS):
        print("ctester-bridge: not configured (token, URL, key or channels "
              "missing) -- nothing to do.", flush=True)
        return 0
    print("ctester-bridge: %d channel(s), polling every %d s"
          % (len(CHANNELS), INTERVAL), flush=True)
    # Without a saved position, start from the latest message instead of replaying history.
    state = read_state()
    for channel in CHANNELS:
        if state.get(channel):
            continue
        try:
            batch = messages(channel, None)
            if batch:
                state[channel] = str(batch[-1].get("id") or "")
        except Exception as error:
            print("ctester-bridge: amorcage impossible :", error, flush=True)
    write_state(state)
    while True:
        write_state(poll_once(state))
        # REST polling instead of the gateway: a few seconds of latency is fine for a course chat.
        time.sleep(INTERVAL)


def autotest():
    assert parse_channels("111=@chat:general") == {"111": "@chat:general"}
    assert parse_channels("111=@chat:general, 222=@chat:tp2-ex3") == {
        "111": "@chat:general", "222": "@chat:tp2-ex3"}
    assert parse_channels("111=tp2-ex3") == {}
    assert parse_channels("abc=@chat:general") == {}
    assert parse_channels("") == {} and parse_channels(None) == {}

    human = {"content": "salut", "author": {"id": "9", "username": "Lea"}}
    assert should_relay(human) is True
    assert should_relay(dict(human, webhook_id="42")) is False
    assert should_relay({"content": "x", "author": {"bot": True}}) is False
    assert should_relay(dict(human, content="   ")) is False
    assert should_relay(None) is False

    assert display_name(human) == "Lea"
    assert display_name(dict(human, member={"nick": "Lea B."})) == "Lea B."
    assert display_name({"author": {}}) == "Discord"
    print("ctester-bridge: autotest ok", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(autotest() if "--autotest" in sys.argv else start())
