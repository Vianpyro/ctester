import asyncio
import json

import config

_rooms = {}

_loop = None


class Connection:
    def __init__(self, socket, key):
        self.socket = socket
        self.key = key

    async def send(self, payload):
        try:
            await self.socket.send_text(json.dumps(payload))
        except Exception:
            pass


def full(key):
    return len(_rooms.get(key, ())) >= config.FORUM_LIVE_MAX


def join(connection):
    global _loop
    if _loop is None:
        try:
            _loop = asyncio.get_running_loop()
        except RuntimeError:
            _loop = None
    _rooms.setdefault(connection.key, []).append(connection)


def leave(connection):
    room = _rooms.get(connection.key)
    if not room:
        return
    if connection in room:
        room.remove(connection)
    if not room:
        _rooms.pop(connection.key, None)


def notify(key):
    # Called from sync endpoints in the threadpool; a failed ring never fails the write.
    if _loop is None or key not in _rooms:
        return
    try:
        _loop.call_soon_threadsafe(lambda: asyncio.ensure_future(_ring(key)))
    except RuntimeError:
        pass


async def _ring(key):
    for member in list(_rooms.get(key, ())):
        await member.send({"t": "new", "thread": key})


def reset():
    _rooms.clear()
