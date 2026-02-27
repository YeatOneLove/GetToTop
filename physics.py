import math
from typing import Any, Dict, Tuple

import pymunk
from pymunk import Vec2d


def _limited_velocity(body: pymunk.Body, gravity: Vec2d, damping: float, dt: float) -> None:
    pymunk.Body.update_velocity(body, gravity, damping, dt)
    max_speed = 600
    max_angular = 10
    if body.velocity.length > max_speed:
        body.velocity = body.velocity.normalized() * max_speed
    body.angular_velocity = max(-max_angular, min(max_angular, body.angular_velocity))


def create_ragdoll(space: pymunk.Space, position: Tuple[float, float]) -> Dict[str, Any]:
    x, y = position

    head_radius = 15
    torso_size = (20, 40)
    leg_length = 35
    leg_thickness = 6

    head_mass = 1
    torso_mass = 3
    leg_mass = 1.5

    head_moment = pymunk.moment_for_circle(head_mass, 0, head_radius)
    head_body = pymunk.Body(head_mass, head_moment)
    head_body.position = x, y
    head_shape = pymunk.Circle(head_body, head_radius)
    head_shape.friction = 0.8
    head_shape.elasticity = 0.0

    torso_width, torso_height = torso_size
    torso_moment = pymunk.moment_for_box(torso_mass, torso_size)
    torso_body = pymunk.Body(torso_mass, torso_moment)
    torso_body.position = x, y + head_radius + torso_height / 2
    torso_shape = pymunk.Poly.create_box(torso_body, torso_size)
    torso_shape.friction = 0.9
    torso_shape.elasticity = 0.0

    leg_moment = pymunk.moment_for_segment(
        leg_mass, (0, 0), (0, leg_length), leg_thickness / 2
    )
    left_leg_body = pymunk.Body(leg_mass, leg_moment)
    right_leg_body = pymunk.Body(leg_mass, leg_moment)
    left_leg_body.position = x - torso_width / 4, torso_body.position.y + torso_height / 2
    right_leg_body.position = x + torso_width / 4, torso_body.position.y + torso_height / 2

    left_leg_shape = pymunk.Segment(left_leg_body, (0, 0), (0, leg_length), leg_thickness / 2)
    right_leg_shape = pymunk.Segment(right_leg_body, (0, 0), (0, leg_length), leg_thickness / 2)
    for leg_shape in (left_leg_shape, right_leg_shape):
        leg_shape.friction = 1.0
        leg_shape.elasticity = 0.0

    for body in (head_body, torso_body, left_leg_body, right_leg_body):
        body.velocity_func = _limited_velocity

    neck_joint = pymunk.PivotJoint(torso_body, head_body, torso_body.local_to_world((0, -torso_height / 2)))
    left_hip_joint = pymunk.PivotJoint(
        torso_body, left_leg_body, torso_body.local_to_world((-torso_width / 4, torso_height / 2))
    )
    right_hip_joint = pymunk.PivotJoint(
        torso_body, right_leg_body, torso_body.local_to_world((torso_width / 4, torso_height / 2))
    )

    neck_limit = pymunk.RotaryLimitJoint(torso_body, head_body, -math.pi / 4, math.pi / 4)
    left_hip_limit = pymunk.RotaryLimitJoint(torso_body, left_leg_body, -math.pi / 3, math.pi / 6)
    right_hip_limit = pymunk.RotaryLimitJoint(torso_body, right_leg_body, -math.pi / 6, math.pi / 3)

    for j in (neck_joint, left_hip_joint, right_hip_joint):
        j.max_force = 2_000
        j.max_bias = 100

    bodies = [head_body, torso_body, left_leg_body, right_leg_body]
    shapes = [head_shape, torso_shape, left_leg_shape, right_leg_shape]
    joints = [neck_joint, left_hip_joint, right_hip_joint, neck_limit, left_hip_limit, right_hip_limit]
    space.add(*(bodies + shapes + joints))

    return {
        "bodies": {"head": head_body, "torso": torso_body, "left_leg": left_leg_body, "right_leg": right_leg_body},
        "shapes": {"head": head_shape, "torso": torso_shape, "left_leg": left_leg_shape, "right_leg": right_leg_shape},
        "joints": {
            "neck": neck_joint,
            "left_hip": left_hip_joint,
            "right_hip": right_hip_joint,
            "neck_limit": neck_limit,
            "left_hip_limit": left_hip_limit,
            "right_hip_limit": right_hip_limit,
        },
    }


def _create_space(width: int, height: int) -> Tuple[pymunk.Space, pymunk.Shape]:
    space = pymunk.Space()
    space.gravity = (0, 700)
    space.damping = 0.9
    space.iterations = 60

    floor_y = height - 50
    floor = pymunk.Segment(space.static_body, (0, floor_y), (width, floor_y), 10)
    floor.friction = 1.0
    floor.elasticity = 0.0
    space.add(floor)
    return space, floor


def _tether_ragdolls(space: pymunk.Space, torso_a: pymunk.Body, torso_b: pymunk.Body) -> pymunk.Constraint:
    joint = pymunk.PinJoint(torso_a, torso_b, (0, 0), (0, 0))
    joint.max_force = 2_500
    joint.max_bias = 80
    joint.error_bias = (1 - 0.01) ** 60
    space.add(joint)
    return joint


def _run_local_test() -> None:
    import pygame
    from pymunk.pygame_util import DrawOptions

    pygame.init()
    width, height = 800, 600
    screen = pygame.display.set_mode((width, height))
    pygame.display.set_caption("Ragdoll Physics Test")
    clock = pygame.time.Clock()

    space, _floor = _create_space(width, height)
    ragdoll1 = create_ragdoll(space, (width / 2 - 80, 200))
    ragdoll2 = create_ragdoll(space, (width / 2 + 80, 200))
    _tether_ragdolls(space, ragdoll1["bodies"]["torso"], ragdoll2["bodies"]["torso"])

    draw_options = DrawOptions(screen)
    dt = 1.0 / 60.0
    running = True

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        screen.fill((30, 30, 40))

        sub_steps = 5
        sub_dt = dt / sub_steps
        for _ in range(sub_steps):
            space.step(sub_dt)

        space.debug_draw(draw_options)
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()


if __name__ == "__main__":
    _run_local_test()

