"""Duck Pond — a live 3D view of your agent fleet, in Blender.

The pure-Python core (model, theme, adapters) imports without Blender so it can be tested
with plain `python`. Everything that needs bpy lives in `addon.py` and is only loaded
when running inside Blender.
"""
try:
    import bpy  # noqa: F401
except ImportError:  # plain Python: core only
    bpy = None

if bpy is not None:
    from .addon import RT, bl_info, build_adapters, register, unregister  # noqa: F401
