"""Build and render the population scene inside Blender (uses only Blender's bundled numpy).

    blender -b --factory-startup -P blender/build_scene.py -- --bundle DIR [--out FILE] [--blend FILE]

DIR holds heights.npz and config.json written by `python -m popspike heights`.
Grid convention: row 0 is north; Blender +X = east, +Y = north, Z = up.
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

HERE = Path(__file__).resolve().parent
PALETTES = json.loads((HERE / "palettes.json").read_text())


def hex_rgba(h, a=1.0):
    h = h.lstrip("#")
    srgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb]
    return (*lin, a)


# ----------------------------------------------------------------------------- geometry

def grid_xy(ny, nx, cell):
    w, h = nx * cell, ny * cell
    xs = (np.arange(nx) + 0.5) * cell - w / 2
    ys = h / 2 - (np.arange(ny) + 0.5) * cell
    return xs, ys


def make_mesh(name, verts, faces_flat, nverts_per_face, attrs, smooth):
    mesh = bpy.data.meshes.new(name)
    nv, nf = len(verts), len(faces_flat) // nverts_per_face
    mesh.vertices.add(nv)
    mesh.vertices.foreach_set("co", verts.astype(np.float32).ravel())
    mesh.loops.add(len(faces_flat))
    mesh.loops.foreach_set("vertex_index", faces_flat.astype(np.int32))
    mesh.polygons.add(nf)
    mesh.polygons.foreach_set("loop_start", np.arange(0, len(faces_flat), nverts_per_face, dtype=np.int32))
    mesh.update(calc_edges=True)
    for key, arr in attrs.items():
        a = mesh.attributes.new(key, "FLOAT", "POINT")
        a.data.foreach_set("value", arr.astype(np.float32))
    if smooth:
        mesh.shade_smooth()
    else:
        mesh.shade_flat()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def terrain(height, land, us, cell, zscale, base, name="terrain", smooth=True):
    """Continuous surface: one vertex per cell centre, quads wherever any corner is land."""
    ny, nx = height.shape
    xs, ys = grid_xy(ny, nx, cell)
    X, Y = np.meshgrid(xs, ys)
    Z = np.where(land > 0, base + height * zscale, 0.0)
    verts = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)
    idx = np.arange(ny * nx).reshape(ny, nx)
    a, b = idx[:-1, :-1], idx[:-1, 1:]
    c, d = idx[1:, 1:], idx[1:, :-1]
    any_land = (land[:-1, :-1] | land[:-1, 1:] | land[1:, 1:] | land[1:, :-1]) > 0
    # counter-clockwise seen from above (row index grows southward)
    quads = np.stack([d[any_land], c[any_land], b[any_land], a[any_land]], axis=1)
    attrs = {"h": height.ravel(), "us": us.ravel().astype(np.float32)}
    return make_mesh(name, verts, quads.ravel(), 4, attrs, smooth)


def columns(height, base_z, sel, us, cell, zscale, footprint, taper, base=0.0, name="spikes"):
    """Square prisms (taper=1) or needles (taper<1), one per selected cell, merged into one mesh."""
    ny, nx = height.shape
    xs, ys = grid_xy(ny, nx, cell)
    ii, jj = np.nonzero(sel)
    n = ii.size
    cx, cy = xs[jj], ys[ii]
    z0 = base_z[ii, jj]
    z1 = np.maximum(z0 + 1e-4, base + height[ii, jj] * zscale)
    hb = footprint * cell / 2
    ht = hb * taper
    sx = np.array([-1, 1, 1, -1], dtype=np.float32)
    sy = np.array([-1, -1, 1, 1], dtype=np.float32)
    bottom = np.stack([cx[:, None] + sx * hb, cy[:, None] + sy * hb, np.repeat(z0[:, None], 4, 1)], -1)
    top = np.stack([cx[:, None] + sx * ht, cy[:, None] + sy * ht, np.repeat(z1[:, None], 4, 1)], -1)
    verts = np.concatenate([bottom, top], axis=1).reshape(-1, 3)
    o = (np.arange(n) * 8)[:, None]
    local = np.array([[0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7], [4, 5, 6, 7]])
    faces = (o[:, None, :] + local[None, :, :]).reshape(-1)
    hv = np.repeat(height[ii, jj], 8)
    # bottom ring gets the base value so a vertical gradient can be read from h_rel
    rel = np.tile(np.array([0, 0, 0, 0, 1, 1, 1, 1], dtype=np.float32), n)
    attrs = {"h": hv, "h_rel": rel, "us": np.repeat(us[ii, jj].astype(np.float32), 8)}
    print(f"  {name}: {n:,} columns")
    return make_mesh(name, verts, faces, 4, attrs, smooth=False)


# ----------------------------------------------------------------------------- shading

def material(name, pal, fog, fog_near, fog_far, attr="h", gamma=1.0, fog_color=None):
    """fog_color: what the surface fades toward with distance (default: the background colour)."""
    mat = bpy.data.materials.new(name)
    if bpy.app.version < (5, 0, 0):
        mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    at = nodes.new("ShaderNodeAttribute"); at.attribute_name = attr
    us = nodes.new("ShaderNodeAttribute"); us.attribute_name = "us"

    pw = nodes.new("ShaderNodeMath"); pw.operation = "POWER"; pw.inputs[1].default_value = gamma
    links.new(at.outputs["Fac"], pw.inputs[0])
    ramp = nodes.new("ShaderNodeValToRGB")
    els = ramp.color_ramp.elements
    stops = pal["ramp"]
    els[0].position, els[0].color = stops[0][0], hex_rgba(stops[0][1])
    els[1].position, els[1].color = stops[-1][0], hex_rgba(stops[-1][1])
    for pos, col in stops[1:-1]:
        e = els.new(pos); e.color = hex_rgba(col)
    links.new(pw.outputs[0], ramp.inputs["Fac"])

    # neighbours: darken colour by neighbor_dim (geometry stays true to data)
    dim = nodes.new("ShaderNodeMath"); dim.operation = "MULTIPLY_ADD"
    dim.inputs[1].default_value = pal["neighbor_dim"]; dim.inputs[2].default_value = 1 - pal["neighbor_dim"]
    links.new(us.outputs["Fac"], dim.inputs[0])
    tint = nodes.new("ShaderNodeMix"); tint.data_type = "RGBA"; tint.blend_type = "MULTIPLY"
    tint.inputs["Factor"].default_value = 1.0
    links.new(ramp.outputs["Color"], tint.inputs[6])
    links.new(dim.outputs[0], tint.inputs[7])
    links.new(tint.outputs[2], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = pal["roughness"]
    bsdf.inputs["Metallic"].default_value = pal["metallic"]

    # restrained emission on the highest values only
    em_r = nodes.new("ShaderNodeMapRange")
    em_r.inputs["From Min"].default_value = pal["emission_from"]
    em_r.inputs["From Max"].default_value = 1.0
    em_r.inputs["To Max"].default_value = pal["emission_strength"]
    links.new(at.outputs["Fac"], em_r.inputs["Value"])
    em_us = nodes.new("ShaderNodeMath"); em_us.operation = "MULTIPLY"
    links.new(em_r.outputs["Result"], em_us.inputs[0]); links.new(dim.outputs[0], em_us.inputs[1])
    bsdf.inputs["Emission Color"].default_value = hex_rgba(pal["emission"])
    links.new(em_us.outputs[0], bsdf.inputs["Emission Strength"])

    # depth fade toward the background colour (cheap atmospheric perspective)
    cam = nodes.new("ShaderNodeCameraData")
    fr = nodes.new("ShaderNodeMapRange")
    fr.inputs["From Min"].default_value = fog_near
    fr.inputs["From Max"].default_value = fog_far
    fr.inputs["To Max"].default_value = fog
    links.new(cam.outputs["View Distance"], fr.inputs["Value"])
    # neighbours recede into the background too (fade = max(depth fog, neighbor_fade * (1 - us)))
    nf = nodes.new("ShaderNodeMath"); nf.operation = "MULTIPLY_ADD"
    nf.inputs[1].default_value = -pal.get("neighbor_fade", 0.0)
    nf.inputs[2].default_value = pal.get("neighbor_fade", 0.0)
    links.new(us.outputs["Fac"], nf.inputs[0])
    fade = nodes.new("ShaderNodeMath"); fade.operation = "MAXIMUM"
    links.new(fr.outputs["Result"], fade.inputs[0]); links.new(nf.outputs[0], fade.inputs[1])
    bg = nodes.new("ShaderNodeEmission"); bg.inputs["Color"].default_value = hex_rgba(fog_color or pal["background"])
    mix = nodes.new("ShaderNodeMixShader")
    links.new(fade.outputs[0], mix.inputs["Fac"])
    links.new(bsdf.outputs["BSDF"], mix.inputs[1])
    links.new(bg.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return mat


def world(pal, light_strength):
    w = bpy.data.worlds.new("World"); bpy.context.scene.world = w
    if bpy.app.version < (5, 0, 0):
        w.use_nodes = True
    nt = w.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    seen = nt.nodes.new("ShaderNodeBackground"); seen.inputs["Color"].default_value = hex_rgba(pal["background"])
    lit = nt.nodes.new("ShaderNodeBackground")
    lit.inputs["Color"].default_value = hex_rgba("#5a6b8c"); lit.inputs["Strength"].default_value = light_strength
    lp = nt.nodes.new("ShaderNodeLightPath")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs["Fac"])
    nt.links.new(lit.outputs[0], mix.inputs[1])
    nt.links.new(seen.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])


def sun(name, azimuth_deg, elevation_deg, strength, angle_deg, color="#ffffff"):
    """azimuth: compass direction the light comes FROM (0 = north, 90 = east)."""
    a, e = math.radians(azimuth_deg), math.radians(elevation_deg)
    to_light = Vector((math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e)))
    ld = bpy.data.lights.new(name, "SUN")
    ld.energy = strength; ld.angle = math.radians(angle_deg); ld.color = hex_rgba(color)[:3]
    ob = bpy.data.objects.new(name, ld)
    ob.rotation_euler = (-to_light).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(ob)


LIGHT_PRESETS = {
    # (azimuth, elevation, strength multiplier, angle, colour), world fill
    "raking_west": ([(255, 14, 1.0, 3, "#fff1dc"), (120, 30, 0.12, 20, "#9fb4ff")], 0.08),
    "top_ao": ([(200, 65, 0.6, 15, "#ffffff")], 0.35),
    "rim": ([(15, 12, 1.2, 2, "#fff0d8"), (220, 35, 0.15, 25, "#9fb4ff")], 0.06),
    "dusk_south": ([(195, 9, 1.0, 4, "#ffd9a8"), (300, 40, 0.1, 20, "#a0b8ff")], 0.07),
}


# ----------------------------------------------------------------------------- main

def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--blend", default=None)
    args = ap.parse_args(argv)
    t0 = time.time()

    bundle = Path(args.bundle)
    cfg = json.loads((bundle / "config.json").read_text())
    data = np.load(bundle / "heights.npz")
    g, r = cfg["geometry"], cfg["render"]
    pal = PALETTES[r["palette"]]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    height, land = data["height"], data["land"]
    us = (data["country"] == 1)
    ny, nx = height.shape
    cell = g["map_width"] / nx
    zmax, base = g["max_height"], g["base_height"]

    # fog distances scale with camera distance
    dist = r["camera"]["distance"]
    near, far = r.get("fog_range", [0.75, 1.6])
    fog_args = (r["fog"], dist * near, dist * far)
    gamma = float(r.get("color_gamma", 1.0))
    # columns may fade toward a neutral dark instead of a tinted background, so the tint never colours the gold
    col_fog = pal.get("column_fog")
    objs = []
    kind = g["type"]
    if kind == "terrain":
        ob = terrain(height, land, us, cell, zmax, base)
        ob.data.materials.append(material("terrain", pal, *fog_args, gamma=gamma)); objs.append(ob)
    elif kind == "spikes":
        s = g["spikes"]
        plate = terrain(np.zeros_like(height), land, us, cell, 0, base, name="plate", smooth=False)
        plate.data.materials.append(material("plate", pal, *fog_args, gamma=gamma))
        sel = (data["value"] >= s["min_value"]) & (land > 0) & (height > 0)
        base_z = np.full(height.shape, base, dtype=np.float32)
        ob = columns(height, base_z, sel, us, cell, zmax, s["footprint"], s["taper"], base)
        ob.data.materials.append(material("spikes", pal, *fog_args, gamma=gamma, fog_color=col_fog)); objs += [plate, ob]
    elif kind == "hybrid":
        hy = g["hybrid"]
        surface, spikes = data["surface"], data["spikes"]
        ob = terrain(surface, land, us, cell, zmax, base, name="surface")
        ob.data.materials.append(material("surface", pal, *fog_args, gamma=gamma))
        base_z = np.where(land > 0, base + surface * zmax, 0).astype(np.float32)
        sel = (spikes > 0) & (land > 0)
        sp = columns(spikes, base_z, sel, us, cell, zmax, hy["spike_footprint"], hy["spike_taper"],
                     base, name="needles")
        sp.data.materials.append(material("needles", pal, *fog_args, gamma=gamma, fog_color=col_fog)); objs += [ob, sp]
    else:
        raise ValueError(kind)

    # sea plane just under the land. "flat": unlit ocean colour, so land floats on darkness and the data
    # extent's edges disappear; "lit": diffuse, catches the long shadows of low light
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 0, -0.002))
    sea = bpy.context.active_object
    sea.scale = (g["map_width"] * 3, g["map_width"] * 3, 1)
    sm = bpy.data.materials.new("sea")
    if bpy.app.version < (5, 0, 0):
        sm.use_nodes = True
    snt = sm.node_tree
    p = snt.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = hex_rgba(pal["ocean"]); p.inputs["Roughness"].default_value = 0.9
    if r.get("sea", "flat") == "flat":
        # emit only toward the camera: a tinted (e.g. navy) sea must not cast coloured light on the columns
        em = snt.nodes.new("ShaderNodeEmission"); em.inputs["Color"].default_value = hex_rgba(pal["ocean"])
        dark = snt.nodes.new("ShaderNodeBsdfDiffuse"); dark.inputs["Color"].default_value = (0, 0, 0, 1)
        lp = snt.nodes.new("ShaderNodeLightPath")
        mx = snt.nodes.new("ShaderNodeMixShader")
        snt.links.new(lp.outputs["Is Camera Ray"], mx.inputs["Fac"])
        snt.links.new(dark.outputs["BSDF"], mx.inputs[1])
        snt.links.new(em.outputs["Emission"], mx.inputs[2])
        snt.links.new(mx.outputs["Shader"], snt.nodes["Material Output"].inputs["Surface"])
    sea.data.materials.append(sm)

    # camera
    cc = r["camera"]
    w_units, h_units = g["map_width"], g["map_width"] * ny / nx
    target = Vector(((cc["target"][0] - 0.5) * w_units, (0.5 - cc["target"][1]) * h_units, 0))
    az, el = math.radians(cc["azimuth_deg"]), math.radians(cc["elevation_deg"])
    offset = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el))) * dist
    cam_d = bpy.data.cameras.new("cam")
    cam_d.lens = cc["focal_mm"]; cam_d.sensor_fit = "HORIZONTAL"; cam_d.sensor_width = 36
    cam_d.shift_x, cam_d.shift_y = cc["shift_x"], cc["shift_y"]
    cam_d.clip_start, cam_d.clip_end = 0.1, dist * 10
    cam = bpy.data.objects.new("cam", cam_d)
    cam.location = target + offset
    cam.rotation_euler = (-offset).to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(cam); scene.camera = cam

    lights, fill = LIGHT_PRESETS[r["light"]["preset"]]
    for i, (laz, lel, mult, ang, col) in enumerate(lights):
        sun(f"sun{i}", laz, lel, r["light"]["strength"] * mult, ang, col)
    world(pal, fill * r["light"].get("world", 1.0))

    # render settings
    rs = scene.render
    rs.resolution_x, rs.resolution_y, rs.resolution_percentage = r["width"], r["height"], 100
    if r["engine"] == "CYCLES":
        rs.engine = "CYCLES"
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for backend in ("OPTIX", "CUDA"):
            try:
                prefs.compute_device_type = backend
                prefs.get_devices()
                gpus = [d for d in prefs.devices if d.type == backend]
                if gpus:
                    for d in prefs.devices:
                        d.use = d.type == backend
                    scene.cycles.device = "GPU"
                    print(f"  cycles on {backend}: {[d.name for d in gpus]}")
                    break
            except TypeError:
                continue
        scene.cycles.samples = r["samples"]
        scene.cycles.use_denoising = r["denoise"]
        scene.cycles.max_bounces = 6
    else:
        rs.engine = "BLENDER_EEVEE" if "BLENDER_EEVEE" in {e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items} else "BLENDER_EEVEE_NEXT"
    vs = scene.view_settings
    vs.view_transform = "AgX"
    try:
        vs.look = r.get("look", "AgX - Medium High Contrast")
    except TypeError:
        pass
    vs.exposure = r.get("exposure", 0.0)
    rs.image_settings.file_format = "PNG"
    rs.image_settings.color_depth = "16"
    rs.image_settings.color_mode = "RGB"

    if args.blend:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.blend).resolve()))
    out = Path(args.out or bundle / "render.png").resolve()
    rs.filepath = str(out)
    print(f"  scene built in {time.time() - t0:.1f}s; rendering {r['width']}x{r['height']} ...")
    bpy.ops.render.render(write_still=True)
    print(f"  rendered in {time.time() - t0:.1f}s -> {out}")


if __name__ == "__main__":
    main()
