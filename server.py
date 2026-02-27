import asyncio
import json
import os
import sys
from typing import Dict, Any, Set

import pymunk
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

# Ensure this project directory is on the Python path so we can import physics.py
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from physics import create_ragdoll, _create_space, tether_players, COLLTYPE_FLOOR, COLLTYPE_HEAD


app = FastAPI()


WIDTH = 800
HEIGHT = 600
TICK_RATE = 60.0


space: pymunk.Space | None = None
ragdolls: Dict[str, Dict[str, Any]] = {}
physics_task: asyncio.Task | None = None
connected_clients: Set[WebSocket] = set()
_floor_shape: pymunk.Shape | None = None

_game_over_until: float | None = None
_pending_game_over_event: Dict[str, Any] | None = None


def _init_world() -> None:
    """
    Initialize the shared Pymunk space and two tethered ragdolls.
    """
    global space, ragdolls, _floor_shape

    space_local, _floor = _create_space(WIDTH, HEIGHT)
    _floor_shape = _floor

    ragdoll1 = create_ragdoll(space_local, (WIDTH / 2 - 80, 200))
    ragdoll2 = create_ragdoll(space_local, (WIDTH / 2 + 80, 200))

    tether_players(space_local, ragdoll1, ragdoll2)

    # Tag heads with a player id for win detection
    ragdoll1["shapes"]["head"].player = 1
    ragdoll2["shapes"]["head"].player = 2

    space = space_local
    ragdolls = {
        "player1": ragdoll1,
        "player2": ragdoll2,
    }

    _install_collision_handlers(space_local)


def _install_collision_handlers(space_local: pymunk.Space) -> None:
    # Pymunk API differs by version:
    # - older: Space.add_collision_handler(...)
    # - newer: Space.on_collision(...)
    if hasattr(space_local, "add_collision_handler"):
        handler = space_local.add_collision_handler(COLLTYPE_HEAD, COLLTYPE_FLOOR)
        handler.begin = _on_head_hits_floor
        return

    # Newer Pymunk (7+) style
    if hasattr(space_local, "on_collision"):
        space_local.on_collision(COLLTYPE_HEAD, COLLTYPE_FLOOR, begin=_on_head_hits_floor)
        return

    raise RuntimeError("Unsupported Pymunk version: no collision handler API found.")


def _on_head_hits_floor(arbiter: pymunk.Arbiter, _space: pymunk.Space, _data: Any) -> bool:
    global _game_over_until, _pending_game_over_event
    if _game_over_until is not None:
        return True

    head_shape = None
    for s in arbiter.shapes:
        if getattr(s, "collision_type", None) == COLLTYPE_HEAD:
            head_shape = s
            break

    loser = int(getattr(head_shape, "player", 0) or 0)
    if loser not in (1, 2):
        return True

    now = asyncio.get_running_loop().time()
    _game_over_until = now + 3.0
    _pending_game_over_event = {"status": "game_over", "loser": loser}
    return True


def _serialize_ragdoll_state(name: str, ragdoll: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert ragdoll bodies into a simple serializable dict:
    { limb_name: { x, y, angle } }
    """
    bodies = ragdoll["bodies"]
    return {
        limb_name: {
            "x": float(body.position.x),
            "y": float(body.position.y),
            "angle": float(body.angle),
        }
        for limb_name, body in bodies.items()
    }


def _build_game_state_payload() -> str:
    """
    Build a JSON string with the current transform of every limb
    for both players.
    """
    state = {
        player_name: _serialize_ragdoll_state(player_name, ragdoll)
        for player_name, ragdoll in ragdolls.items()
    }
    return json.dumps(state)


async def _broadcast_state() -> None:
    """
    Send the current game state to all connected WebSocket clients.
    """
    if not connected_clients:
        return

    payload = _build_game_state_payload()
    coros = []
    for ws in list(connected_clients):
        coros.append(_safe_send(ws, payload))
    await asyncio.gather(*coros, return_exceptions=True)


async def _broadcast_event(event: Dict[str, Any]) -> None:
    if not connected_clients:
        return
    payload = json.dumps(event)
    await asyncio.gather(*[_safe_send(ws, payload) for ws in list(connected_clients)], return_exceptions=True)

async def _safe_send(ws: WebSocket, text: str) -> None:
    try:
        await ws.send_text(text)
    except Exception:
        # On any send error, drop the client
        if ws in connected_clients:
            connected_clients.remove(ws)


async def _physics_loop() -> None:
    """
    Background task that advances the Pymunk simulation
    and broadcasts the latest game state at ~60 Hz.
    """
    assert space is not None
    dt = 1.0 / TICK_RATE

    global _pending_game_over_event, _game_over_until

    while True:
        now = asyncio.get_running_loop().time()

        if _pending_game_over_event is not None:
            await _broadcast_event(_pending_game_over_event)
            _pending_game_over_event = None

        if _game_over_until is not None and now < _game_over_until:
            # Freeze simulation during game over, but keep streaming state.
            await _broadcast_state()
            await asyncio.sleep(dt)
            continue

        if _game_over_until is not None and now >= _game_over_until:
            _reset_world()

        # Multiple small steps per tick can help with stability.
        sub_steps = 6
        sub_dt = dt / sub_steps
        for _ in range(sub_steps):
            space.step(sub_dt)

        await _broadcast_state()
        await asyncio.sleep(dt)


def _reset_world() -> None:
    global _game_over_until, _pending_game_over_event
    _game_over_until = None
    _pending_game_over_event = None
    _init_world()

def _apply_action(player: int, action: str) -> None:
    """
    Apply an impulse to the chosen player's torso.
    player: 1 or 2
    action: 'jump' | 'left' | 'right'
    """
    # Ignore input while game over is showing
    if _game_over_until is not None:
        return

    player_key = "player1" if player == 1 else "player2"
    torso: pymunk.Body = ragdolls[player_key]["bodies"]["torso"]

    mass = float(torso.mass)
    if action == "jump":
        # Note: +y is down in this project, so jump is negative y impulse.
        torso.apply_impulse_at_local_point((0.0, -260.0 * mass), (0, 0))
        return

    if action == "left":
        torso.apply_impulse_at_local_point((-140.0 * mass, 0.0), (0, -10))
        return

    if action == "right":
        torso.apply_impulse_at_local_point((140.0 * mass, 0.0), (0, -10))
        return


def _parse_input_message(text: str) -> tuple[int, str] | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    action = data.get("action")
    player = data.get("player")
    if action not in {"jump", "left", "right"}:
        return None
    if player not in {1, 2}:
        return None
    return int(player), str(action)


@app.on_event("startup")
async def on_startup() -> None:
    """
    Initialize world and start physics loop when the server starts.
    """
    global physics_task
    _init_world()
    physics_task = asyncio.create_task(_physics_loop())


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """
    Cleanly stop the physics loop on shutdown.
    """
    global physics_task
    if physics_task is not None:
        physics_task.cancel()
        try:
            await physics_task
        except asyncio.CancelledError:
            pass


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """
    WebSocket endpoint that streams the current game state as JSON.
    For now, it only sends state; later we will also receive input.
    """
    await websocket.accept()
    connected_clients.add(websocket)

    try:
        while True:
            # If the broadcaster dropped this socket (send failure), exit.
            if websocket not in connected_clients:
                return
            # Client input messages (optional) — state streaming is independent.
            try:
                text = await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            parsed = _parse_input_message(text)
            if parsed is None:
                continue
            player, action = parsed
            _apply_action(player, action)
    except WebSocketDisconnect:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
    except Exception:
        if websocket in connected_clients:
            connected_clients.remove(websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)

