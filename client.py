import asyncio
import json
import math
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import pygame


WS_URL = "wss://edythe-aquiline-rick.ngrok-free.dev/ws"
WIDTH = 800
HEIGHT = 600
FPS = 60
WORLD_MARGIN = 30
CEILING_Y = WORLD_MARGIN
FLOOR_Y = HEIGHT - 50


@dataclass
class LimbState:
    x: float
    y: float
    angle: float


GameState = Dict[str, Dict[str, LimbState]]  # player -> limb -> state


def _parse_state(message: str) -> GameState:
    raw = json.loads(message)
    parsed: GameState = {}
    for player_name, limbs in raw.items():
        parsed[player_name] = {}
        for limb_name, s in limbs.items():
            parsed[player_name][limb_name] = LimbState(
                x=float(s["x"]),
                y=float(s["y"]),
                angle=float(s["angle"]),
            )
    return parsed


def _rotate(v: Tuple[float, float], angle: float) -> Tuple[float, float]:
    x, y = v
    c = math.cos(angle)
    s = math.sin(angle)
    return (x * c - y * s, x * s + y * c)


def _draw_ragdoll(screen: pygame.Surface, ragdoll: Dict[str, LimbState], color: Tuple[int, int, int]) -> None:
    head = ragdoll.get("head")
    torso = ragdoll.get("torso")
    left_leg = ragdoll.get("left_leg")
    right_leg = ragdoll.get("right_leg")
    left_arm = ragdoll.get("left_arm")
    right_arm = ragdoll.get("right_arm")

    if torso is not None:
        torso_half = 20
        dx, dy = _rotate((0, torso_half), torso.angle)
        p1 = (int(torso.x - dx), int(torso.y - dy))
        p2 = (int(torso.x + dx), int(torso.y + dy))
        pygame.draw.line(screen, color, p1, p2, 6)

    if head is not None:
        pygame.draw.circle(screen, color, (int(head.x), int(head.y)), 15)

    def draw_leg(leg: Optional[LimbState]) -> None:
        if leg is None:
            return
        leg_len = 35
        dx, dy = _rotate((0, leg_len), leg.angle)
        p1 = (int(leg.x), int(leg.y))
        p2 = (int(leg.x + dx), int(leg.y + dy))
        pygame.draw.line(screen, color, p1, p2, 5)

    draw_leg(left_leg)
    draw_leg(right_leg)

    def draw_arm(arm: Optional[LimbState], direction: int) -> None:
        if arm is None:
            return
        arm_len = 30 * direction
        dx, dy = _rotate((arm_len, 0), arm.angle)
        p1 = (int(arm.x), int(arm.y))
        p2 = (int(arm.x + dx), int(arm.y + dy))
        pygame.draw.line(screen, color, p1, p2, 5)

    # left arm points left, right arm points right (based on how server built segments)
    draw_arm(left_arm, -1)
    draw_arm(right_arm, 1)


def _hand_endpoint(arm: LimbState, direction: int) -> Tuple[float, float]:
    arm_len = 30 * direction
    dx, dy = _rotate((arm_len, 0), arm.angle)
    return arm.x + dx, arm.y + dy


def _build_action_payload(action: str, player: int) -> str:
    return json.dumps({"action": action, "player": player})


class WsStateClient:
    def __init__(self, url: str, player: int) -> None:
        self.url = url
        self.player = player
        self._latest: Dict[str, Any] = {"state": None, "game_over_until": None, "game_over_loser": None}
        self._lock = threading.Lock()

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._send_q: Optional[asyncio.Queue[str]] = None
        self._thread = threading.Thread(target=self._runner, daemon=True)
        self._thread.start()

    def get_state(self) -> Optional["GameState"]:
        with self._lock:
            return self._latest["state"]

    def get_game_over(self) -> tuple[Optional[float], Optional[int]]:
        with self._lock:
            return self._latest["game_over_until"], self._latest["game_over_loser"]

    def send_action(self, action: str) -> None:
        loop = self._loop
        q = self._send_q
        if loop is None or q is None:
            return
        payload = _build_action_payload(action, self.player)
        loop.call_soon_threadsafe(q.put_nowait, payload)

    def _runner(self) -> None:
        asyncio.run(self._ws_main())

    async def _ws_main(self) -> None:
        try:
            import websockets  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "Missing dependency. Install with: python -m pip install websockets"
            ) from e

        self._loop = asyncio.get_running_loop()
        self._send_q = asyncio.Queue()

        async with websockets.connect(self.url) as ws:
            recv_task = asyncio.create_task(self._recv_loop(ws))
            send_task = asyncio.create_task(self._send_loop(ws))
            done, pending = await asyncio.wait(
                {recv_task, send_task}, return_when=asyncio.FIRST_EXCEPTION
            )
            for t in pending:
                t.cancel()
            for t in done:
                exc = t.exception()
                if exc is not None:
                    raise exc

    async def _recv_loop(self, ws: Any) -> None:
        async for msg in ws:
            try:
                data = json.loads(msg)
            except json.JSONDecodeError:
                continue

            if isinstance(data, dict) and data.get("status") == "game_over":
                loser = data.get("loser")
                if loser in (1, 2):
                    with self._lock:
                        self._latest["game_over_until"] = time.monotonic() + 3.0
                        self._latest["game_over_loser"] = int(loser)
                continue

            # Otherwise, treat it as a state payload (player1/player2 limbs)
            state = _parse_state(msg)
            with self._lock:
                self._latest["state"] = state

    async def _send_loop(self, ws: Any) -> None:
        assert self._send_q is not None
        while True:
            payload = await self._send_q.get()
            await ws.send(payload)


def _parse_player_arg(argv: list[str]) -> int:
    # Usage: python client.py --player 1
    if "--player" in argv:
        i = argv.index("--player")
        if i + 1 < len(argv):
            try:
                p = int(argv[i + 1])
                if p in (1, 2):
                    return p
            except ValueError:
                pass
    return 1


def _action_from_key(key: int) -> Optional[str]:
    if key == pygame.K_UP:
        return "jump"
    if key == pygame.K_LEFT:
        return "left"
    if key == pygame.K_RIGHT:
        return "right"
    return None


def run_client() -> None:
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    player = _parse_player_arg(sys.argv)
    pygame.display.set_caption(f"GetToTop - Client (Player {player})")
    clock = pygame.time.Clock()

    ws_client = WsStateClient(WS_URL, player=player)

    running = True
    while running:
        go_until, go_loser = ws_client.get_game_over()
        is_game_over = go_until is not None and time.monotonic() < go_until

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                action = _action_from_key(event.key)
                if action is not None and not is_game_over:
                    ws_client.send_action(action)

        screen.fill((25, 25, 35))
        border_color = (120, 120, 140)
        pygame.draw.line(screen, border_color, (WORLD_MARGIN, FLOOR_Y), (WIDTH - WORLD_MARGIN, FLOOR_Y), 4)
        pygame.draw.line(screen, border_color, (WORLD_MARGIN, CEILING_Y), (WIDTH - WORLD_MARGIN, CEILING_Y), 4)
        pygame.draw.line(screen, border_color, (WORLD_MARGIN, CEILING_Y), (WORLD_MARGIN, FLOOR_Y), 4)
        pygame.draw.line(screen, border_color, (WIDTH - WORLD_MARGIN, CEILING_Y), (WIDTH - WORLD_MARGIN, FLOOR_Y), 4)

        state = ws_client.get_state()

        if state is not None:
            _draw_ragdoll(screen, state.get("player1", {}), (220, 80, 80))
            _draw_ragdoll(screen, state.get("player2", {}), (80, 180, 220))

            # Draw the tether line (player1 right hand -> player2 left hand)
            p1 = state.get("player1", {})
            p2 = state.get("player2", {})
            arm_a = p1.get("right_arm")
            arm_b = p2.get("left_arm")
            if arm_a is not None and arm_b is not None:
                a_hand = _hand_endpoint(arm_a, 1)
                b_hand = _hand_endpoint(arm_b, -1)
                pygame.draw.line(
                    screen,
                    (200, 200, 220),
                    (int(a_hand[0]), int(a_hand[1])),
                    (int(b_hand[0]), int(b_hand[1])),
                    3,
                )
        else:
            font = pygame.font.Font(None, 28)
            text = font.render("Connecting to server...", True, (220, 220, 230))
            screen.blit(text, (20, 20))

        if is_game_over:
            font = pygame.font.Font(None, 64)
            loser = go_loser if go_loser in (1, 2) else None
            winner = 2 if loser == 1 else 1 if loser == 2 else None
            msg = "Game Over"
            if winner is not None:
                msg = f"Game Over - Player {winner} wins!"
            text = font.render(msg, True, (245, 245, 255))
            rect = text.get_rect(center=(WIDTH // 2, HEIGHT // 2))
            screen.blit(text, rect)

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()


if __name__ == "__main__":
    run_client()

