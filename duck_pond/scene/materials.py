"""Materials. Everything colour-variable reads Object Info so one material serves many objects."""
from __future__ import annotations

import bpy

from ..theme import hex_to_rgba

PREFIX = "DP_"


def _blended(mat: bpy.types.Material) -> None:
    """Sorted alpha blending. Only small effects use it (rings, packets, bubbles, fading ducks);
    the water is opaque, so blended objects never end up sorted behind it. Dithered/hashed
    transparency was tried first: it sparkles at 1 sample per frame during playback."""
    for attr, val in (("surface_render_method", "BLENDED"), ("blend_method", "BLEND")):
        try:
            setattr(mat, attr, val)
        except (AttributeError, TypeError):
            pass
    try:
        mat.use_backface_culling = False
    except AttributeError:
        pass


def _new(name: str) -> tuple[bpy.types.Material, bpy.types.NodeTree, bpy.types.Node]:
    mat = bpy.data.materials.new(PREFIX + name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    return mat, nt, bsdf


def _get(name: str):
    return bpy.data.materials.get(PREFIX + name)


def _set(bsdf, key, value):
    if key in bsdf.inputs:
        bsdf.inputs[key].default_value = value


def flat_material(name: str, hex_color: str, roughness: float = 0.5, emission: float = 0.0) -> bpy.types.Material:
    mat = _get(name)
    if mat:
        return mat
    mat, nt, bsdf = _new(name)
    rgba = hex_to_rgba(hex_color)
    _set(bsdf, "Base Color", rgba)
    _set(bsdf, "Roughness", roughness)
    if emission:
        _set(bsdf, "Emission Color", rgba)
        _set(bsdf, "Emission Strength", emission)
    return mat


def object_color_material(name: str, roughness: float = 0.35, emission: float = 0.0,
                          coat: float = 0.0, alpha_from_object: bool = True) -> bpy.types.Material:
    """Base colour (and alpha) come from obj.color."""
    mat = _get(name)
    if mat:
        return mat
    mat, nt, bsdf = _new(name)
    info = nt.nodes.new("ShaderNodeObjectInfo")
    info.location = (-400, 0)
    nt.links.new(info.outputs["Color"], bsdf.inputs["Base Color"])
    if alpha_from_object and "Alpha" in info.outputs:
        nt.links.new(info.outputs["Alpha"], bsdf.inputs["Alpha"])
        _blended(mat)
    _set(bsdf, "Roughness", roughness)
    if coat and "Coat Weight" in bsdf.inputs:
        _set(bsdf, "Coat Weight", coat)
    if emission:
        nt.links.new(info.outputs["Color"], bsdf.inputs["Emission Color"])
        _set(bsdf, "Emission Strength", emission)
    return mat


def duck_body_material() -> bpy.types.Material:
    """Body colour from obj.color; emission strength from the object property dp_glow so the
    ducks light up after dark (and a pinned duck can glow)."""
    mat = _get("DuckBody")
    if mat:
        return mat
    mat = object_color_material("DuckBody", roughness=0.3, coat=0.4)
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    info = next((n for n in nt.nodes if n.bl_idname == "ShaderNodeObjectInfo"), None)
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_type = "OBJECT"
    attr.attribute_name = "dp_glow"
    if info is not None:
        nt.links.new(info.outputs["Color"], bsdf.inputs["Emission Color"])
    nt.links.new(attr.outputs["Fac"], bsdf.inputs["Emission Strength"])
    return mat


def ring_material() -> bpy.types.Material:
    return object_color_material("Ring", roughness=0.2, emission=1.5)


def packet_material() -> bpy.types.Material:
    mat = _get("Packet")
    if mat:
        return mat
    mat, nt, bsdf = _new("Packet")
    info = nt.nodes.new("ShaderNodeObjectInfo")
    nt.links.new(info.outputs["Color"], bsdf.inputs["Emission Color"])
    nt.links.new(info.outputs["Color"], bsdf.inputs["Base Color"])
    if "Alpha" in info.outputs:
        nt.links.new(info.outputs["Alpha"], bsdf.inputs["Alpha"])
    _set(bsdf, "Emission Strength", 6.0)
    _set(bsdf, "Roughness", 0.2)
    _blended(mat)
    return mat


def tether_material() -> bpy.types.Material:
    """Colour from obj.color, emission strength from the object property dp_pulse."""
    mat = _get("Tether")
    if mat:
        return mat
    mat, nt, bsdf = _new("Tether")
    info = nt.nodes.new("ShaderNodeObjectInfo")
    nt.links.new(info.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(info.outputs["Color"], bsdf.inputs["Emission Color"])
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_type = "OBJECT"
    attr.attribute_name = "dp_pulse"
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = 5.0
    nt.links.new(attr.outputs["Fac"], mul.inputs[0])
    nt.links.new(mul.outputs[0], bsdf.inputs["Emission Strength"])
    _set(bsdf, "Roughness", 0.6)
    return mat


def bubble_material() -> bpy.types.Material:
    mat = _get("Bubble")
    if mat:
        return mat
    mat, nt, bsdf = _new("Bubble")
    info = nt.nodes.new("ShaderNodeObjectInfo")
    nt.links.new(info.outputs["Color"], bsdf.inputs["Base Color"])
    if "Alpha" in info.outputs:
        nt.links.new(info.outputs["Alpha"], bsdf.inputs["Alpha"])
    _set(bsdf, "Roughness", 0.05)
    if "Transmission Weight" in bsdf.inputs:
        _set(bsdf, "Transmission Weight", 0.6)
    _blended(mat)
    return mat


def text_material() -> bpy.types.Material:
    return flat_material("Text", "#FFFFFF", roughness=0.8, emission=1.2)


def water_material() -> bpy.types.Material:
    mat = _get("Water")
    if mat:
        return mat
    mat, nt, bsdf = _new("Water")
    _set(bsdf, "Base Color", (0.05, 0.36, 0.60, 1.0))
    _set(bsdf, "Roughness", 0.06)
    _set(bsdf, "IOR", 1.33)
    if "Coat Weight" in bsdf.inputs:
        _set(bsdf, "Coat Weight", 0.6)

    # Time driver: a Value node whose output is frame * speed
    tval = nt.nodes.new("ShaderNodeValue")
    tval.name = "DP_Time"
    tval.label = "time"
    tval.location = (-1100, 0)
    try:
        fc = nt.driver_add('nodes["DP_Time"].outputs[0].default_value')
        fc.driver.type = "SCRIPTED"
        fc.driver.expression = "frame * 0.012"
    except Exception as exc:  # driver creation is best-effort
        print("[duck_pond] water time driver failed:", exc)

    coords = nt.nodes.new("ShaderNodeTexCoord")
    coords.location = (-1100, -200)

    def ripple_layer(scale, speed_x, speed_y, detail, y):
        comb = nt.nodes.new("ShaderNodeCombineXYZ")
        comb.location = (-900, y)
        mx = nt.nodes.new("ShaderNodeMath")
        mx.operation = "MULTIPLY"
        mx.inputs[1].default_value = speed_x
        mx.location = (-1000, y + 60)
        my = nt.nodes.new("ShaderNodeMath")
        my.operation = "MULTIPLY"
        my.inputs[1].default_value = speed_y
        my.location = (-1000, y - 60)
        nt.links.new(tval.outputs[0], mx.inputs[0])
        nt.links.new(tval.outputs[0], my.inputs[0])
        nt.links.new(mx.outputs[0], comb.inputs["X"])
        nt.links.new(my.outputs[0], comb.inputs["Y"])
        add = nt.nodes.new("ShaderNodeVectorMath")
        add.operation = "ADD"
        add.location = (-750, y)
        nt.links.new(coords.outputs["Object"], add.inputs[0])
        nt.links.new(comb.outputs[0], add.inputs[1])
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.location = (-550, y)
        noise.inputs["Scale"].default_value = scale
        noise.inputs["Detail"].default_value = detail
        if "Roughness" in noise.inputs:
            noise.inputs["Roughness"].default_value = 0.55
        nt.links.new(add.outputs[0], noise.inputs["Vector"])
        return noise

    n1 = ripple_layer(0.9, 1.0, 0.35, 4.0, 200)
    n2 = ripple_layer(2.3, -0.6, 0.8, 3.0, -200)
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "FLOAT"
    mix.location = (-350, 0)
    mix.inputs["Factor"].default_value = 0.45
    nt.links.new(n1.outputs["Fac"], mix.inputs["A"])
    nt.links.new(n2.outputs["Fac"], mix.inputs["B"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.location = (-150, -100)
    bump.inputs["Strength"].default_value = 0.5
    bump.inputs["Distance"].default_value = 0.12
    nt.links.new(mix.outputs["Result"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def tile_material(name: str = "Tile", color1: str = "#6FB7D6", color2: str = "#F2F6F7", scale: float = 6.0) -> bpy.types.Material:
    mat = _get(name)
    if mat:
        return mat
    mat, nt, bsdf = _new(name)
    brick = nt.nodes.new("ShaderNodeTexBrick")
    brick.location = (-400, 0)
    brick.inputs["Scale"].default_value = scale
    brick.inputs["Color1"].default_value = hex_to_rgba(color1)
    brick.inputs["Color2"].default_value = hex_to_rgba(color1)
    brick.inputs["Mortar"].default_value = hex_to_rgba(color2)
    brick.inputs["Mortar Size"].default_value = 0.015
    coords = nt.nodes.new("ShaderNodeTexCoord")
    coords.location = (-600, 0)
    nt.links.new(coords.outputs["Object"], brick.inputs["Vector"])
    nt.links.new(brick.outputs["Color"], bsdf.inputs["Base Color"])
    _set(bsdf, "Roughness", 0.25)
    return mat


def deck_material() -> bpy.types.Material:
    return flat_material("Deck", "#D8D2C4", roughness=0.9)


def lane_rope_material() -> bpy.types.Material:
    return object_color_material("LaneRope", roughness=0.5, alpha_from_object=False)


# ---------------------------------------------------------------- reimagined additions
def object_text_material() -> bpy.types.Material:
    """Emissive text whose colour (and alpha) come from obj.color: one material for every chip."""
    mat = _get("ObjText")
    if mat:
        return mat
    mat, nt, bsdf = _new("ObjText")
    info = nt.nodes.new("ShaderNodeObjectInfo")
    nt.links.new(info.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(info.outputs["Color"], bsdf.inputs["Emission Color"])
    if "Alpha" in info.outputs:
        nt.links.new(info.outputs["Alpha"], bsdf.inputs["Alpha"])
    _set(bsdf, "Emission Strength", 2.0)
    _set(bsdf, "Roughness", 0.8)
    _blended(mat)
    return mat


def glow_material() -> bpy.types.Material:
    """Strongly emissive, colour + alpha from obj.color: beacons, risers, drops, coins of light."""
    mat = _get("Glow")
    if mat:
        return mat
    mat, nt, bsdf = _new("Glow")
    info = nt.nodes.new("ShaderNodeObjectInfo")
    nt.links.new(info.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(info.outputs["Color"], bsdf.inputs["Emission Color"])
    if "Alpha" in info.outputs:
        nt.links.new(info.outputs["Alpha"], bsdf.inputs["Alpha"])
    _set(bsdf, "Emission Strength", 8.0)
    _set(bsdf, "Roughness", 0.3)
    _blended(mat)
    return mat


def beacon_material() -> bpy.types.Material:
    """Like glow_material but calmer, so red stays red instead of blowing out to white."""
    mat = _get("Beacon")
    if mat:
        return mat
    mat, nt, bsdf = _new("Beacon")
    info = nt.nodes.new("ShaderNodeObjectInfo")
    nt.links.new(info.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(info.outputs["Color"], bsdf.inputs["Emission Color"])
    _set(bsdf, "Emission Strength", 2.5)
    _set(bsdf, "Roughness", 0.4)
    return mat


def halo_material() -> bpy.types.Material:
    """State halo: colour + alpha from obj.color, soft emission so it reads on water by day and night."""
    mat = _get("Halo")
    if mat:
        return mat
    mat, nt, bsdf = _new("Halo")
    info = nt.nodes.new("ShaderNodeObjectInfo")
    nt.links.new(info.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(info.outputs["Color"], bsdf.inputs["Emission Color"])
    if "Alpha" in info.outputs:
        nt.links.new(info.outputs["Alpha"], bsdf.inputs["Alpha"])
    # Low on purpose: the scene uses Blender's default AgX view, which pushes bright emission toward
    # white, and at 2.2 a yellow "waiting" halo rendered cream and teal went pale.
    _set(bsdf, "Emission Strength", 0.7)
    _set(bsdf, "Roughness", 0.6)
    _blended(mat)
    return mat


def board_material() -> bpy.types.Material:
    return flat_material("Board", "#0E1320", roughness=0.7)


def coin_material() -> bpy.types.Material:
    mat = flat_material("Coin", "#F2B632", roughness=0.25)
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    _set(bsdf, "Metallic", 1.0)
    return mat


def water_set_chop(mat: bpy.types.Material, chop: float) -> None:
    """0 = glassy, 1 = busy. Bump strength and ripple scroll speed follow the fleet's throughput."""
    nt = mat.node_tree
    bump = next((n for n in nt.nodes if n.bl_idname == "ShaderNodeBump"), None)
    if bump is not None:
        bump.inputs["Strength"].default_value = 0.25 + 0.75 * chop
        bump.inputs["Distance"].default_value = 0.06 + 0.18 * chop
    speed = nt.nodes.get("DP_Chop")
    if speed is None:
        speed = nt.nodes.new("ShaderNodeValue")
        speed.name = "DP_Chop"
        speed.label = "chop"
    speed.outputs[0].default_value = chop


def water_set_night(mat: bpy.types.Material, night: float) -> None:
    """Darker, bluer water at night so the lit ducks and lane lights read."""
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is None:
        return
    day = (0.05, 0.36, 0.60)
    nite = (0.02, 0.09, 0.22)
    c = tuple(day[i] * (1 - night) + nite[i] * night for i in range(3))
    _set(bsdf, "Base Color", (*c, 1.0))
