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

## Game Physics

The simulation uses [Pymunk](https://www.pymunk.org/) (a Chipmunk2D wrapper) for 2D rigid-body physics. All values below are defined in `physics.py` and `server.py`.

### World

| Property | Value | Notes |
|----------|-------|-------|
| Gravity | `(0, 500)` | Downward; slightly reduced for better control |
| Damping | `0.95` | Per-body velocity damping for stability |
| Solver iterations | `150` | Higher = more stable joints |
| Sleep threshold | `0.3` s | Bodies can sleep when idle |

The arena is a box: floor, ceiling, and side walls. Floor and walls use `friction = 1.0`, `elasticity = 0.0`. The floor has a special collision type for head-touch detection.

### Ragdoll Structure

Each player is a 6-body ragdoll:

| Limb | Shape | Mass | Dimensions |
|------|-------|------|------------|
| Head | Circle | 1.2 | radius 15 |
| Torso | Box | 4.0 | 24×40 |
| Left/Right leg | Segment | 2.0 each | length 35, thickness 7 |
| Left/Right arm | Segment | 1.2 each | length 30, thickness 5 |

The torso is the main mass; legs and arms are lighter. Legs have higher friction (1.5) and slight elasticity (0.1) for grip and a bit of bounce.

### Joints

Each limb is attached to the torso with a **PivotJoint** (keeps attachment point fixed) plus a **RotaryLimitJoint** (limits rotation):

| Joint | Angle limits (rad) | Purpose |
|-------|--------------------|---------|
| Neck | ±π/3 (~±60°) | Head can tilt forward/back |
| Left hip | -π/2 to π/3 | Leg can swing back and forward |
| Right hip | -π/3 to π/2 | Same, mirrored |
| Left shoulder | -π to π/3 | Arm can swing widely |
| Right shoulder | -π/3 to π | Same, mirrored |

Joint constraints use `max_force = 300_000` and `max_bias = 3_000` so limbs stay attached under strong impulses. Rotary limits use `max_force = 200_000`, `max_bias = 2_500`.

### Velocity Limits

A custom `velocity_func` caps linear and angular speed to avoid runaway motion:

- **Max linear speed**: 900 units/s  
- **Max angular speed**: ±20 rad/s  

### Player Tether

Player 1’s right hand and Player 2’s left hand are connected by a **DampedSpring**:

| Property | Value |
|----------|-------|
| Rest length | 120 |
| Stiffness | 8000 |
| Damping | 400 |

The spring pulls the hands toward each other when stretched and pushes when compressed, so players can push and pull through the tether. A `PinJoint` would be too rigid; the spring allows some give.

### Player Input (Impulses)

Input is applied as impulses to the torso and legs (arms are not driven directly):

| Action | Effect |
|--------|--------|
| **Jump** | Upward impulse: torso `350 × mass`, each leg `350 × 0.3 × mass` |
| **Left** | Horizontal impulse: torso `-180 × mass` (at local `(0, -5)`), legs `-180 × 0.4/0.6 × mass`; torso `angular_velocity += -2` |
| **Right** | Same as left but mirrored: `+180`, `angular_velocity += +2` |

Asymmetric leg forces (0.4 vs 0.6) help with turning. The offset impulse on the torso adds a leaning effect.

### Stabilization

For the first 3 seconds after spawn or reset, a small stabilizing torque is applied to the torso when it leans too much (`|angle| > 0.2`): `torque = -angle × 800`. This reduces immediate tipping before players gain control.

### Simulation Loop

- Fixed timestep: `1/60` s per tick  
- 6 sub-steps per tick for stability  
- State broadcast to all clients after each tick  

### Win Detection

The floor shape uses `collision_type = COLLTYPE_FLOOR`. A collision handler checks when a shape with `collision_type = COLLTYPE_HEAD` hits the floor. The head shape stores a `player` attribute (1 or 2); that player is declared the loser.

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
