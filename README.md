# GetToTop

A real-time multiplayer physics game inspired by "Get On Top." Two ragdoll players are tethered by the hands and compete to push each other over. The first player whose head hits the floor loses.

## Architecture

| Component | File | Description |
|-----------|------|-------------|
| **Server** | `server.py` | FastAPI WebSocket server. Runs a Pymunk physics simulation at 60 FPS and broadcasts game state to all connected clients. Accepts player input (jump, left, right) over WebSocket. |
| **Client** | `client.py` | Pygame client. Connects to the server via WebSocket, renders both ragdolls in real time, and sends keyboard input. |
| **Physics** | `physics.py` | Pymunk-based ragdoll creation, joint constraints, tethering between players, and world boundaries (floor, ceiling, walls). |

## How It Works

- **Ragdolls**: Each player is a physics ragdoll with head, torso, legs, and arms. Limbs are connected with pivot joints and rotary limits.
- **Tether**: Player 1's right hand and Player 2's left hand are connected by a damped spring, so they can push and pull each other.
- **Win condition**: If a player's head touches the floor, that player loses. The game shows "Game Over" for 3 seconds, then resets both ragdolls to standing positions.

## Requirements

- Python 3.10+
- [Pymunk](https://www.pymunk.org/) – 2D physics
- [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) – WebSocket server
- [Pygame](https://www.pygame.org/) – Client rendering
- [websockets](https://websockets.readthedocs.io/) – WebSocket client

```bash
pip install pymunk fastapi uvicorn pygame websockets
```

## Running the Game

### 1. Start the server

```bash
python server.py
```

The server listens on `http://0.0.0.0:8000` and exposes a WebSocket at `/ws`.

### 2. Start two clients

In separate terminals:

```bash
python client.py --player 1
python client.py --player 2
```

Each client connects to the server and renders the shared game state. Player 1 is red, Player 2 is blue.

### 3. Remote play (e.g. ngrok)

To play over the internet, expose the server with [ngrok](https://ngrok.com/) or similar:

```bash
ngrok http 8000
```

Then set `WS_URL` in `client.py` to the ngrok WebSocket URL (use `wss://` for HTTPS tunnels):

```python
WS_URL = "wss://your-subdomain.ngrok-free.dev/ws"
```

For local development, use:

```python
WS_URL = "ws://127.0.0.1:8000/ws"
```

## Controls

| Key | Action |
|-----|--------|
| ↑ | Jump |
| ← | Move left |
| → | Move right |

## WebSocket Protocol

- **Server → Client**: JSON object with limb positions for both players:
  ```json
  {
    "player1": { "head": {"x": 320, "y": 450, "angle": 0}, "torso": {...}, ... },
    "player2": { ... }
  }
  ```
  Special event for game over:
  ```json
  { "status": "game_over", "loser": 1 }
  ```

- **Client → Server**: JSON object for player actions:
  ```json
  { "action": "jump" | "left" | "right", "player": 1 | 2 }
  ```

## Project Structure

```
GetToTop/
├── server.py      # FastAPI + physics loop + WebSocket handler
├── client.py      # Pygame client + WebSocket state sync
├── physics.py     # Ragdoll creation, tethering, world setup
├── main.py        # (Unused – PyCharm template)
└── README.md
```
