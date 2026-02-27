import math
from typing import Any, Dict, Tuple

import pymunk
from pymunk import Vec2d

COLLTYPE_HEAD = 1
COLLTYPE_FLOOR = 2


def _limited_velocity(body: pymunk.Body, gravity: Vec2d, damping: float, dt: float) -> None:
    pymunk.Body.update_velocity(body, gravity, damping, dt)
    max_speed = 900
    max_angular = 16
    if body.velocity.length > max_speed:
        body.velocity = body.velocity.normalized() * max_speed
    body.angular_velocity = max(-max_angular, min(max_angular, body.angular_velocity))


_ragdoll_group_counter = 1


def _next_collision_group() -> int:
    global _ragdoll_group_counter
    _ragdoll_group_counter += 1
    return _ragdoll_group_counter


def create_ragdoll(
    space: pymunk.Space, position: Tuple[float, float], *, collision_group: int | None = None
) -> Dict[str, Any]:
    x, y = position

    head_radius = 15
    torso_size = (20, 40)
    leg_length = 35
    leg_thickness = 6
    arm_length = 30
    arm_thickness = 5

    head_mass = 1
    torso_mass = 3
    leg_mass = 1.5
    arm_mass = 1.0

    # Strong constraints so limbs stay attached even under impulses.
    joint_max_force = 200_000
    joint_max_bias = 2_000
    limit_max_force = 120_000
    limit_max_bias = 1_500

    group = collision_group if collision_group is not None else _next_collision_group()
    ragdoll_filter = pymunk.ShapeFilter(group=group)

    head_moment = pymunk.moment_for_circle(head_mass, 0, head_radius)
    head_body = pymunk.Body(head_mass, head_moment)
    head_body.position = x, y
    head_shape = pymunk.Circle(head_body, head_radius)
    head_shape.friction = 0.8
    head_shape.elasticity = 0.0
    head_shape.filter = ragdoll_filter
    head_shape.collision_type = COLLTYPE_HEAD
    head_shape.label = "Head"

    torso_width, torso_height = torso_size
    torso_moment = pymunk.moment_for_box(torso_mass, torso_size)
    torso_body = pymunk.Body(torso_mass, torso_moment)
    torso_body.position = x, y + head_radius + torso_height / 2
    torso_shape = pymunk.Poly.create_box(torso_body, torso_size)
    torso_shape.friction = 0.9
    torso_shape.elasticity = 0.0
    torso_shape.filter = ragdoll_filter

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
        leg_shape.filter = ragdoll_filter

    # Arms (shoulders -> hands)
    left_arm_moment = pymunk.moment_for_segment(arm_mass, (0, 0), (-arm_length, 0), arm_thickness / 2)
    right_arm_moment = pymunk.moment_for_segment(arm_mass, (0, 0), (arm_length, 0), arm_thickness / 2)
    left_arm_body = pymunk.Body(arm_mass, left_arm_moment)
    right_arm_body = pymunk.Body(arm_mass, right_arm_moment)

    shoulder_y = torso_body.position.y - torso_height / 4
    left_arm_body.position = x - torso_width / 2, shoulder_y
    right_arm_body.position = x + torso_width / 2, shoulder_y

    left_arm_shape = pymunk.Segment(left_arm_body, (0, 0), (-arm_length, 0), arm_thickness / 2)
    right_arm_shape = pymunk.Segment(right_arm_body, (0, 0), (arm_length, 0), arm_thickness / 2)
    for arm_shape in (left_arm_shape, right_arm_shape):
        arm_shape.friction = 0.9
        arm_shape.elasticity = 0.0
        arm_shape.filter = ragdoll_filter

    for body in (head_body, torso_body, left_leg_body, right_leg_body):
        body.velocity_func = _limited_velocity
    for body in (left_arm_body, right_arm_body):
        body.velocity_func = _limited_velocity

    neck_joint = pymunk.PivotJoint(torso_body, head_body, torso_body.local_to_world((0, -torso_height / 2)))
    left_hip_joint = pymunk.PivotJoint(
        torso_body, left_leg_body, torso_body.local_to_world((-torso_width / 4, torso_height / 2))
    )
    right_hip_joint = pymunk.PivotJoint(
        torso_body, right_leg_body, torso_body.local_to_world((torso_width / 4, torso_height / 2))
    )

    left_shoulder_joint = pymunk.PivotJoint(
        torso_body, left_arm_body, torso_body.local_to_world((-torso_width / 2, -torso_height / 4))
    )
    right_shoulder_joint = pymunk.PivotJoint(
        torso_body, right_arm_body, torso_body.local_to_world((torso_width / 2, -torso_height / 4))
    )

    neck_limit = pymunk.RotaryLimitJoint(torso_body, head_body, -math.pi / 4, math.pi / 4)
    left_hip_limit = pymunk.RotaryLimitJoint(torso_body, left_leg_body, -math.pi / 3, math.pi / 6)
    right_hip_limit = pymunk.RotaryLimitJoint(torso_body, right_leg_body, -math.pi / 6, math.pi / 3)
    left_shoulder_limit = pymunk.RotaryLimitJoint(torso_body, left_arm_body, -math.pi / 2, math.pi / 6)
    right_shoulder_limit = pymunk.RotaryLimitJoint(torso_body, right_arm_body, -math.pi / 6, math.pi / 2)

    for j in (neck_joint, left_hip_joint, right_hip_joint, left_shoulder_joint, right_shoulder_joint):
        j.max_force = joint_max_force
        j.max_bias = joint_max_bias

    for j in (neck_limit, left_hip_limit, right_hip_limit, left_shoulder_limit, right_shoulder_limit):
        j.max_force = limit_max_force
        j.max_bias = limit_max_bias

    bodies = [head_body, torso_body, left_leg_body, right_leg_body, left_arm_body, right_arm_body]
    shapes = [head_shape, torso_shape, left_leg_shape, right_leg_shape, left_arm_shape, right_arm_shape]
    joints = [
        neck_joint,
        left_hip_joint,
        right_hip_joint,
        left_shoulder_joint,
        right_shoulder_joint,
        neck_limit,
        left_hip_limit,
        right_hip_limit,
        left_shoulder_limit,
        right_shoulder_limit,
    ]
    space.add(*(bodies + shapes + joints))

    return {
        "bodies": {
            "head": head_body,
            "torso": torso_body,
            "left_leg": left_leg_body,
            "right_leg": right_leg_body,
            "left_arm": left_arm_body,
            "right_arm": right_arm_body,
        },
        "shapes": {
            "head": head_shape,
            "torso": torso_shape,
            "left_leg": left_leg_shape,
            "right_leg": right_leg_shape,
            "left_arm": left_arm_shape,
            "right_arm": right_arm_shape,
        },
        "joints": {
            "neck": neck_joint,
            "left_hip": left_hip_joint,
            "right_hip": right_hip_joint,
            "left_shoulder": left_shoulder_joint,
            "right_shoulder": right_shoulder_joint,
            "neck_limit": neck_limit,
            "left_hip_limit": left_hip_limit,
            "right_hip_limit": right_hip_limit,
            "left_shoulder_limit": left_shoulder_limit,
            "right_shoulder_limit": right_shoulder_limit,
        },
    }


def _create_space(width: int, height: int) -> Tuple[pymunk.Space, pymunk.Shape]:
    space = pymunk.Space()
    space.gravity = (0, 700)
    space.damping = 0.9
    space.iterations = 120
    space.sleep_time_threshold = 0.5

    margin = 30
    thickness = 10

    ceiling_y = margin
    floor_y = height - 50

    floor = pymunk.Segment(space.static_body, (margin, floor_y), (width - margin, floor_y), thickness)
    floor.friction = 1.0
    floor.elasticity = 0.0
    floor.collision_type = COLLTYPE_FLOOR
    floor.label = "Floor"

    left_wall = pymunk.Segment(space.static_body, (margin, ceiling_y), (margin, floor_y), thickness)
    right_wall = pymunk.Segment(
        space.static_body, (width - margin, ceiling_y), (width - margin, floor_y), thickness
    )
    ceiling = pymunk.Segment(space.static_body, (margin, ceiling_y), (width - margin, ceiling_y), thickness)

    for s in (left_wall, right_wall, ceiling):
        s.friction = 1.0
        s.elasticity = 0.0

    space.add(floor, left_wall, right_wall, ceiling)
    return space, floor


def _tether_ragdolls(space: pymunk.Space, torso_a: pymunk.Body, torso_b: pymunk.Body) -> pymunk.Constraint:
    joint = pymunk.PinJoint(torso_a, torso_b, (0, 0), (0, 0))
    joint.max_force = 2_500
    joint.max_bias = 80
    joint.error_bias = (1 - 0.01) ** 60
    space.add(joint)
    return joint


def tether_players(space: pymunk.Space, ragdoll_a: Dict[str, Any], ragdoll_b: Dict[str, Any]) -> pymunk.Constraint:
    """
    Connect players together by their hands (arm ends).
    Player A right hand <-> Player B left hand.
    """
    arm_length = 30
    right_arm_a: pymunk.Body = ragdoll_a["bodies"]["right_arm"]
    left_arm_b: pymunk.Body = ragdoll_b["bodies"]["left_arm"]

    joint = pymunk.PinJoint(right_arm_a, left_arm_b, (arm_length, 0), (-arm_length, 0))
    joint.max_force = 250_000
    joint.max_bias = 3_000
    joint.error_bias = (1 - 0.02) ** 60
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
    tether_players(space, ragdoll1, ragdoll2)

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

