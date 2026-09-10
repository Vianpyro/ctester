"""The live collaboration relay: rooms, presence, and nothing else.

WHAT THIS MODULE IS NOT. It is not a CRDT, and it does not know what a
character is. Teams edit with Yjs in the browser (an npm dependency bundled
into the team workspace's own chunk), and this
process forwards the opaque frames Yjs produces from one member of a room to
the others, verbatim. That split is the whole design:

  * the convergence guarantee is Yjs's, which is a proven implementation --
    not a merge protocol invented here and debugged during a lab session;
  * the AUTHORIZATION is ours, and it is enforced on the frame's SENDER, not
    on anything the frame contains. A member cannot forge a room, a team or
    another member's caret by writing different bytes, because the room and
    the sender's handle are decided when the socket is accepted and stamped
    onto every frame afterwards;
  * the durable copy of the work is plain text in Postgres
    (`team_document`), written over HTTP through the same `validate_files`
    allow-list as every other path. Nothing that only exists as a CRDT blob
    can be handed in, so nothing here can corrupt a hand-in.

CURSORS AND PRESENCE ARE EPHEMERAL AND STAY THAT WAY. They live in this
dict, they die with the process, and they are never written to Postgres --
a caret position is not state, it is a fact about the next two seconds.

ONE WORKER, and this module is one more reason for it (see `app/main.py`).
The rooms are process memory: a second uvicorn worker would put two members
of the same team in two different rooms, which would look exactly like a
network problem and would not be one.

ponytail: the room is dropped as soon as its last member leaves, and the
document is then reseeded from Postgres by whoever arrives next. The seam is
`epoch` -- a fresh id per room -- which a returning client compares against
the one it synced with: a different epoch means "start from the server's copy",
so a stale local document can never be merged into a reseeded one and double
the text. Keeping the CRDT state in memory between sessions would remove the
reseed; it would also mean a room that never dies, and this is a course
platform that closes in December.
"""

import json

import config

# room key -> {"epoch": str, "members": [Connection]}. Touched ONLY from the
# event loop (the WebSocket handler), never from the threadpool the HTTP
# endpoints run in -- which is why there is no lock here and why there must
# not be a reason to add one.
_rooms = {}


class Connection:
    """One open socket: who it is, where it is, and how to write to it.

    `handle` IS ASSIGNED BY THE SERVER from the roster, and it is the only
    identity that ever reaches another member. The socket never carries a
    `sub`, so there is nothing here to leak into a teammate's browser.
    """

    def __init__(self, socket, key, handle, account):
        self.socket = socket
        self.key = key
        self.handle = handle
        self.account = account

    async def send(self, payload):
        """One JSON frame. A dead socket is not an error to propagate.

        A member whose browser went away mid-broadcast must not take the
        broadcast down for the three who are still typing.
        """
        try:
            await self.socket.send_text(json.dumps(payload))
        except Exception:
            pass


def room_key(team_id, exercise_id):
    """The room's name. Both halves are already proven by the caller's gate.

    THE TEAM IS IN THE KEY, which is what makes cross-team leakage
    structurally impossible rather than filtered: two teams working on the
    same exercise are two different rooms, and a member is only ever put in
    the room built from the team the database returned for them.
    """
    return team_id + "\x00" + exercise_id


def join(connection):
    """Puts the connection in its room. Returns (epoch, peers already there).

    `peers` IS WHAT DECIDES WHO SEEDS THE DOCUMENT. The first client into an
    empty room fills its Yjs document from the server's plain-text copy; every
    later one asks the room for it instead. Without that distinction, two
    clients seeding the same text into a CRDT would merge into the text twice
    -- and the join order is decided here, in one process, so there is no race
    to lose.
    """
    room = _rooms.get(connection.key)
    if room is None or len(room["members"]) == 0:
        room = {"epoch": _epoch(), "members": []}
        _rooms[connection.key] = room
    peers = len(room["members"])
    room["members"].append(connection)
    return room["epoch"], peers


def full(key):
    """True when the room already holds as many sockets as it accepts.

    A bound, not a policy: a team is three or four, and the margin covers
    someone with two tabs open. What it stops is one account opening a
    thousand sockets on a service with a single worker.
    """
    room = _rooms.get(key)
    return bool(room) and len(room["members"]) >= config.TEAM_LIVE_MAX


def leave(connection):
    """Removes the connection, and the room with it when it was the last one."""
    room = _rooms.get(connection.key)
    if room is None:
        return
    room["members"] = [m for m in room["members"] if m is not connection]
    if not room["members"]:
        _rooms.pop(connection.key, None)


def members(key):
    """The handles currently connected in this room, in join order, deduplicated.

    Deduplicated because one member with two tabs is one person: a presence
    list that showed "Coéquipier 2" twice would read as a fifth teammate.
    """
    room = _rooms.get(key)
    seen, out = set(), []
    for member in (room or {}).get("members", ()):
        if member.handle not in seen:
            seen.add(member.handle)
            out.append(member.handle)
    return out


async def broadcast(connection, payload):
    """Sends to everyone in the room EXCEPT the sender.

    The sender already has its own change -- it is the one that made it --
    and echoing it back would make every keystroke a round trip.
    """
    room = _rooms.get(connection.key)
    for member in list((room or {}).get("members", ())):
        if member is not connection:
            await member.send(payload)


async def announce(key):
    """Tells the room who is in it now. Sent on every join and every leave."""
    room = _rooms.get(key)
    payload = {"t": "presence", "online": members(key)}
    for member in list((room or {}).get("members", ())):
        await member.send(payload)


def _epoch():
    import uuid

    return uuid.uuid4().hex


def reset():
    """Empties every room. FOR TESTS ONLY -- production rooms die with the process."""
    _rooms.clear()
