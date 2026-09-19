"""Pool geometry, water, lanes, lighting, cameras."""
from __future__ import annotations

import math
import time

import bpy
from mathutils import Vector

from ..theme import hex_to_rgba
from . import materials as M
from . import meshes as MS

COLL_NAME = "DuckPond"
POOL_X = 16.0
POOL_Y = 8.0
DEPTH = 1.5
DECK = 2.0
GRASS_X, GRASS_Y = 90.0, 70.0  # the lawn: big enough to fill the frame at any window shape
WATER_Z = 0.0
MIN_LANE_W = 2.0
LANE_MARGIN = 0.9
X_MARGIN = 1.4

CAM_OVERVIEW = (Vector((POOL_X / 2 - 1.6, -9.4, 8.2)), Vector((POOL_X / 2 - 1.6, POOL_Y / 2 + 0.8, 0.0)))


def collection() -> bpy.types.Collection:
    coll = bpy.data.collections.get(COLL_NAME)
    if coll is None:
        coll = bpy.data.collections.new(COLL_NAME)
        bpy.context.scene.collection.children.link(coll)
    return coll


def link(obj: bpy.types.Object) -> bpy.types.Object:
    coll = collection()
    if obj.name not in coll.objects:
        coll.objects.link(obj)
    return obj


def new_object(name: str, data=None) -> bpy.types.Object:
    obj = bpy.data.objects.new(name, data)
    return link(obj)


def get(name: str):
    return bpy.data.objects.get(name)


def look_at(obj: bpy.types.Object, target: Vector) -> None:
    direction = target - obj.location
    if direction.length < 1e-6:
        return
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def camera() -> bpy.types.Object:
    cam = get("DP_Camera")
    if cam is None:
        cam_data = bpy.data.cameras.new("DP_Camera")
        cam_data.lens = 29
        cam_data.clip_end = 500
        cam = new_object("DP_Camera", cam_data)
        cam.location = CAM_OVERVIEW[0]
        look_at(cam, CAM_OVERVIEW[1])
    bpy.context.scene.camera = cam
    return cam


def camera_overview() -> None:
    cam = camera()
    cam.location = CAM_OVERVIEW[0]
    look_at(cam, CAM_OVERVIEW[1])


def camera_lane(y0: float, y1: float) -> None:
    cam = camera()
    yc = (y0 + y1) / 2
    cam.location = Vector((POOL_X / 2, yc - 5.5, 3.2))
    look_at(cam, Vector((POOL_X / 2, yc, 0.0)))


def ensure_pool() -> None:
    scene = bpy.context.scene
    collection()
    if get("DP_Water"):
        camera()
        return

    tile = M.tile_material()
    floor_tile = M.tile_material("FloorTile", "#2F7FB8", "#DCEBF3", 4.0)
    deck = M.deck_material()
    chrome = M.flat_material("Chrome", "#C8CCD2", roughness=0.15)

    floor = new_object("DP_Floor", MS.grid_mesh("Floor", POOL_X, POOL_Y, 1, 1, floor_tile))
    floor.location = (0, 0, -DEPTH)
    for name, sx, sy, at in (
        ("DP_WallS", POOL_X, 0.1, (POOL_X / 2, -0.05, -DEPTH / 2)),
        ("DP_WallN", POOL_X, 0.1, (POOL_X / 2, POOL_Y + 0.05, -DEPTH / 2)),
        ("DP_WallW", 0.1, POOL_Y + 0.2, (-0.05, POOL_Y / 2, -DEPTH / 2)),
        ("DP_WallE", 0.1, POOL_Y + 0.2, (POOL_X + 0.05, POOL_Y / 2, -DEPTH / 2)),
    ):
        wall = new_object(name, MS.box_mesh(name[3:], sx, sy, DEPTH + 0.1, tile))
        wall.location = at
    for name, sx, sy, at in (
        ("DP_DeckS", POOL_X + 2 * DECK, DECK, (POOL_X / 2, -DECK / 2 - 0.1, 0.05)),
        ("DP_DeckN", POOL_X + 2 * DECK, DECK, (POOL_X / 2, POOL_Y + DECK / 2 + 0.1, 0.05)),
        ("DP_DeckW", DECK, POOL_Y + 0.2, (-DECK / 2 - 0.1, POOL_Y / 2, 0.05)),
        ("DP_DeckE", DECK, POOL_Y + 0.2, (POOL_X + DECK / 2 + 0.1, POOL_Y / 2, 0.05)),
    ):
        slab = new_object(name, MS.box_mesh(name[3:], sx, sy, 0.1, deck))
        slab.location = at

    # the lawn runs well past the deck so a window wider than the render still lands on grass
    grass = new_object("DP_Grass", MS.grid_mesh("Grass", GRASS_X, GRASS_Y, 1, 1, M.grass_material()))
    grass.location = (POOL_X / 2 - GRASS_X / 2, POOL_Y / 2 - GRASS_Y / 2, -0.015)
    grass["dp_kind"] = "deck"

    water = new_object("DP_Water", MS.grid_mesh("Water", POOL_X, POOL_Y, 64, 32, M.water_material()))
    water.location = (0, 0, WATER_Z)
    water["dp_kind"] = "water"

    ladder = new_object("DP_Ladder", MS.ladder_mesh(chrome))
    ladder.location = (POOL_X - 0.3, POOL_Y - 0.8, 0.0)
    for i, y in enumerate((POOL_Y * 0.25, POOL_Y * 0.75)):
        blk = new_object(f"DP_Block{i}", MS.box_mesh("StartBlock", 0.6, 0.6, 0.5, M.flat_material("BlockBlue", "#2C6FB5")))
        blk.location = (POOL_X + 0.7, y, 0.35)

    # lighting + world
    if not get("DP_Sun"):
        sun_data = bpy.data.lights.new("DP_Sun", "SUN")
        sun_data.energy = 4.0
        sun_data.angle = math.radians(2.0)
        sun_data.color = (1.0, 0.93, 0.82)
        sun = new_object("DP_Sun", sun_data)
        sun.location = (POOL_X / 2, POOL_Y / 2, 20)
        sun.rotation_euler = (math.radians(55), 0.0, math.radians(-35))
    world = bpy.data.worlds.get("DP_World")
    if world is None:
        world = bpy.data.worlds.new("DP_World")
        world.use_nodes = True
        nt = world.node_tree
        bg = nt.nodes.get("Background")
        # plain sky gradient: light blue above, hazy near the horizon (cheap, predictable in EEVEE)
        coords = nt.nodes.new("ShaderNodeTexCoord")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(coords.outputs["Generated"], sep.inputs[0])
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].position = 0.45
        ramp.color_ramp.elements[0].color = (0.75, 0.85, 0.95, 1.0)
        ramp.color_ramp.elements[1].position = 0.75
        ramp.color_ramp.elements[1].color = (0.30, 0.52, 0.85, 1.0)
        nt.links.new(sep.outputs["Z"], ramp.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = 1.0
    scene.world = world

    camera()
    scene.render.fps = 30
    scene.frame_start = 1
    scene.frame_end = 1_000_000
    apply_viewport_settings(scene)
    try:
        scene.render.engine = "BLENDER_EEVEE"
    except TypeError:
        try:
            scene.render.engine = "BLENDER_EEVEE_NEXT"
        except TypeError:
            pass


def apply_viewport_settings(scene) -> None:
    """Cheap-but-clean EEVEE: full-resolution viewport, no shadow/raytrace cost, few samples."""
    try:
        scene.render.preview_pixel_size = "1"  # AUTO halves the viewport on HiDPI -> blurry
    except (AttributeError, TypeError):
        pass
    ee = getattr(scene, "eevee", None)
    if ee is not None:
        for attr, val in (("taa_samples", 4), ("taa_render_samples", 16), ("use_raytracing", False),
                          ("use_shadows", False), ("shadow_ray_count", 1), ("shadow_step_count", 1),
                          ("use_volumetric_shadows", False), ("fast_gi_method", "GLOBAL_ILLUMINATION")):
            try:
                setattr(ee, attr, val)
            except (AttributeError, TypeError):
                pass
    sun = bpy.data.lights.get("DP_Sun")
    if sun is not None:
        try:
            sun.use_shadow = False
        except AttributeError:
            pass


# ---------------------------------------------------------------- text badges
def _badge_mesh() -> bpy.types.Mesh:
    me = bpy.data.meshes.get("DP_Badge")
    if me is None:
        me = bpy.data.meshes.new("DP_Badge")
        me.from_pydata([(-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.5, 0.5, 0.0), (-0.5, 0.5, 0.0)], [], [(0, 1, 2, 3)])
        me.materials.append(M.flat_material("Badge", "#0B0F14", roughness=0.9))
    return me


def add_badge(text_obj: bpy.types.Object) -> bpy.types.Object:
    """A dark plate behind screen-aligned white text, so a name reads the same over water, the
    white deck and other ducks. A child of the text, so it shares its billboard rotation and
    hover properties. Size it with fit_badge once the text has a body."""
    plate = new_object(text_obj.name + "_badge", _badge_mesh())
    plate.parent = text_obj
    for k in ("dp_kind", "dp_session_id", "dp_agent_id"):
        if k in text_obj:
            plate[k] = text_obj[k]
    plate.hide_viewport = True
    plate.hide_render = True
    text_obj["dp_badge"] = plate.name
    return plate


def fit_badge(text_obj: bpy.types.Object, pad: float = 0.3) -> None:
    """Size the badge to the text's evaluated bounds plus `pad` × font size. Evaluates the
    depsgraph, so call it from a timer, never from a frame-change handler."""
    plate = bpy.data.objects.get(text_obj.get("dp_badge", ""))
    if plate is None:
        return
    show = bool(text_obj.data.body.strip()) and not text_obj.hide_viewport
    if plate.hide_viewport == show:
        plate.hide_viewport = not show
        plate.hide_render = not show
    if not show:
        return
    ev = text_obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    xs = [c[0] for c in ev.bound_box]
    ys = [c[1] for c in ev.bound_box]
    p = text_obj.data.size * pad
    plate.location = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, -0.05 * text_obj.data.size)
    plate.scale = (max(xs) - min(xs) + 2 * p, max(ys) - min(ys) + 1.4 * p, 1.0)


# ---------------------------------------------------------------- lanes
LANE_LINGER_S = 180.0  # a lane outlives its last session this long before the pool re-spaces


class Lanes:
    """Assigns a horizontal lane (y range) per working directory.

    Every re-layout moves every duck, so the layout is made as stable as the data allows:
    lanes keep their order (a new directory takes the next slot instead of everything being
    re-sorted), and a lane lingers LANE_LINGER_S after its last session ended, so a session
    that finishes and restarts, or a demo loop, does not re-space the pool every time."""

    def __init__(self) -> None:
        self.keys: list[str] = []
        self.bounds: dict[str, tuple[float, float]] = {}
        self.objects: list[bpy.types.Object] = []
        self.last_seen: dict[str, float] = {}

    def y_range(self, key: str) -> tuple[float, float]:
        return self.bounds.get(key, (0.5, POOL_Y - 0.5))

    def update(self, keys: list[str], now: float | None = None) -> bool:
        now = time.time() if now is None else now
        present = set(keys)
        for k in present:
            self.last_seen[k] = now
        kept = [k for k in self.keys if k in present or now - self.last_seen.get(k, -1e18) < LANE_LINGER_S]
        keys = kept + sorted(present - set(kept))
        if keys == self.keys:
            return False
        for k in list(self.last_seen):
            if k not in keys:
                del self.last_seen[k]
        self.keys = keys
        n = max(1, len(keys))
        # Lanes always share the pool (a MIN_LANE_W floor used to push the fifth lane off the
        # deck), and the margin that keeps a duck's centre off the ropes scales with the lane:
        # a fixed 0.9 left four 2.0 m lanes with a 0.2 m strip to swim in, so every duck
        # bounced between its ropes a few times a second.
        w = POOL_Y / n
        margin = min(LANE_MARGIN, w * 0.22)
        self.bounds = {}
        for i, k in enumerate(keys):
            y0 = i * w
            y1 = (i + 1) * w
            self.bounds[k] = (y0 + margin, max(y0 + margin + 0.2, y1 - margin))
        self._rebuild(w)
        return True

    def _rebuild(self, w: float) -> None:
        for o in self.objects:
            try:
                bpy.data.objects.remove(o, do_unlink=True)
            except ReferenceError:
                pass
        self.objects = []
        rope_mat = M.lane_rope_material()
        for i, key in enumerate(self.keys):
            if i > 0:
                rope = new_object(f"DP_LaneRope_{i}", MS.lane_rope_mesh(POOL_X, rope_mat))
                rope.location = (0, i * w, WATER_Z + 0.02)
                rope.color = hex_to_rgba("#E53935" if i % 2 else "#FAFAFA")
                self.objects.append(rope)
            # the lane's name, branches, sessions and spend live on one sign: deck.LaneSigns
