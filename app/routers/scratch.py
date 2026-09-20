import asyncio
import json
import time

import config
import deps
import headers
import security
import state
from deps import Sub, throttle_write
from fastapi import APIRouter, Request, WebSocket
from schemas import ScratchIn
from services import scratch, spool
from starlette.concurrency import run_in_threadpool

router = APIRouter(tags=["console"])

RELAYED = ("stdin", "eof")

TIC = 0.05


@router.get("/scratch/draft")
def get_scratch_draft(sub: Sub):
    draft = state.read_scratch(sub)
    if draft is None:
        return headers.error(503, "la base ne répond pas")
    return draft


@router.put("/scratch/draft")
def put_scratch_draft(sub: Sub, body: ScratchIn, request: Request):
    code, message, status = scratch.validate_scratch(body.code)
    if message:
        return headers.error(status, message)
    name, header, message, status = scratch.validate_header(body.header_name, body.header)
    if message:
        return headers.error(status, message)
    throttle_write(request)
    if not state.write_scratch(sub, code, name, header):
        return headers.error(503, "la base ne répond pas")
    return {"ok": True}


@router.websocket("/scratch/live")
async def live(socket: WebSocket):
    opening = await deps.hello(socket, 2 * config.MAX_CODE + 4096)
    if opening is None:
        return
    token, code = opening.get("token"), opening.get("code")
    if not isinstance(token, str) or not token or not isinstance(code, str):
        await socket.close(code=deps.CLOSE_BAD)
        return
    code, message, _ = scratch.validate_scratch(code)
    if message:
        await socket.close(code=deps.CLOSE_BAD)
        return
    header_name, header, message, _ = scratch.validate_header(
        opening.get("header_name", ""), opening.get("header", ""))
    if message:
        await socket.close(code=deps.CLOSE_BAD)
        return

    if not config.SCRATCH:
        await socket.close(code=deps.CLOSE_UNAVAILABLE)
        return

    sub = await run_in_threadpool(security.current_user,
                                  {"Authorization": "Bearer " + token})
    if not sub:
        await socket.close(code=deps.CLOSE_UNAUTHORIZED)
        return

    with deps.lock:
        if sub in _open_sessions:
            await socket.close(code=deps.CLOSE_BUSY)
            return
        wait = deps.scratch_quota.check(sub, time.time())
        if wait:
            await socket.close(code=deps.CLOSE_BUSY)
            return
        _open_sessions.add(sub)

    session = None
    try:
        session = await run_in_threadpool(scratch.open_session, code, header_name, header)
        reader = asyncio.create_task(_listen(socket, session))
        await _follow(socket, session, reader)
    except Exception:
        pass
    finally:
        with deps.lock:
            _open_sessions.discard(sub)
        if session is not None:
            session.close()
        try:
            await socket.close()
        except Exception:
            pass


_open_sessions = set()


async def _listen(socket, session):
    while True:
        raw = await socket.receive_text()
        if len(raw) > config.SCRATCH_FRAME + 256:
            break
        try:
            frame = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(frame, dict) or frame.get("t") not in RELAYED:
            continue
        if frame.get("t") == "eof":
            await run_in_threadpool(session.close_input)
            continue
        data = frame.get("d")
        if not isinstance(data, str) or not data:
            continue
        if len(data.encode("utf-8")) > config.SCRATCH_FRAME:
            continue
        if not await run_in_threadpool(session.write_input, data):
            break


async def _follow(socket, session, reader):
    wait, claimed, finished, ticks = 0.0, False, False, 0
    misses = 0
    running = False
    try:
        while True:
            if not claimed:
                claimed = await run_in_threadpool(session.is_claimed)
                if claimed:
                    await _send(socket, {"t": "ready"})
                else:
                    wait += TIC
                    if wait > config.SCRATCH_START_TIMEOUT:
                        await socket.close(code=deps.CLOSE_UNAVAILABLE)
                        return
                    if ticks % 40 == 0:
                        await _send(socket, _queue_frame(session))
                    ticks += 1
                    await asyncio.sleep(TIC)
                    continue

            status = await run_in_threadpool(session.status)
            for name in ("build", "out"):
                text = await run_in_threadpool(session.read_output, name)
                if text:
                    await _send(socket, {"t": name, "d": text})

            if not running and status and status.get("state") == "running":
                running = True
                await _send(socket, {"t": "running"})

            if finished:
                await _send(socket, {"t": "exit",
                                     "code": status.get("code", -1),
                                     "reason": status.get("reason", "exited")})
                return
            if status and status.get("state") == "exited":
                finished = True
            elif not await run_in_threadpool(session.worker_alive):
                misses += 1
                if misses >= 2:
                    await _send(socket, {"t": "exit", "code": -1,
                                         "reason": "worker"})
                    return
            else:
                misses = 0
            await asyncio.sleep(TIC)
    finally:
        reader.cancel()


def _queue_frame(session):
    jobs = spool.scan_jobs()
    return {"t": "queued",
            "position": spool.queue_position(jobs, session.job_id),
            "eta": spool.eta_seconds(jobs, session.job_id)}


async def _send(socket, payload):
    await socket.send_text(json.dumps(payload))
