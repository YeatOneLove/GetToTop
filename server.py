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

from physics import create_ragdoll, _create_space, _tether_ragdolls


app = FastAPI()


WIDTH = 800
HEIGHT = 600
TICK_RATE = 60.0


space: pymunk.Space | None = None
ragdolls: Dict[str, Dict[str, Any]] = {}
physics_task: asyncio.Task | None = None
connected_clients: Set[WebSocket] = set()


def _init_world() -> None:
    """
    Initialize the shared Pymunk space and two tethered ragdolls.
    """
    global space, ragdolls

    space_local, _floor = _create_space(WIDTH, HEIGHT)

    ragdoll1 = create_ragdoll(space_local, (WIDTH / 2 - 80, 200))
    ragdoll2 = create_ragdoll(space_local, (WIDTH / 2 + 80, 200))

    _tether_ragdolls(space_local, ragdoll1["bodies"]["torso"], ragdoll2["bodies"]["torso"])

    space = space_local
    ragdolls = {
        "player1": ragdoll1,
        "player2": ragdoll2,
    }


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

    while True:
        # Multiple small steps per tick can help with stability.
        sub_steps = 3
        sub_dt = dt / sub_steps
        for _ in range(sub_steps):
            space.step(sub_dt)

        await _broadcast_state()
        await asyncio.sleep(dt)


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
        # Keep the connection alive by waiting for incoming messages.
        # We ignore content for now; this will later be used for player input.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
    except Exception:
        if websocket in connected_clients:
            connected_clients.remove(websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)

