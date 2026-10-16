#!/usr/bin/env python3
"""Dissect the resimo scene10.glb to recover the exterior-view rig.

No deps: parses GLB chunks + accessors by hand.
"""
import json, struct, sys, math, re
from collections import Counter, defaultdict

PATH = sys.argv[1] if len(sys.argv) > 1 else "../assets/scene10.glb"

with open(PATH, "rb") as f:
    blob = f.read()

magic, version, total = struct.unpack_from("<III", blob, 0)
assert magic == 0x46546C67, "not a glb"
off, chunks = 12, {}
while off < total:
    clen, ctype = struct.unpack_from("<II", blob, off)
    chunks[ctype] = blob[off + 8: off + 8 + clen]
    off += 8 + clen + (-clen % 4)
G = json.loads(chunks[0x4E4F534A].decode("utf-8"))
BIN = chunks.get(0x004E4942, b"")

NODES = G["nodes"]
name_of = lambda i: NODES[i].get("name", f"<{i}>")

# ---------------------------------------------------------------- hierarchy
parent = {}
for i, n in enumerate(NODES):
    for c in n.get("children", []):
        parent[c] = i

def path_of(i):
    out = []
    while i is not None:
        out.append(name_of(i))
        i = parent.get(i)
    return " / ".join(reversed(out))

print("=" * 78)
print("ASSET :", G.get("asset"))
print("counts: nodes=%d meshes=%d materials=%d cameras=%d anims=%d" % (
    len(NODES), len(G.get("meshes", [])), len(G.get("materials", [])),
    len(G.get("cameras", [])), len(G.get("animations", []))))
print("materials:", [m.get("name") for m in G.get("materials", [])])

print("\n" + "=" * 78)
print("TOP-LEVEL HIERARCHY (depth 3)")
def walk(i, d=0, maxd=3):
    n = NODES[i]
    kids = n.get("children", [])
    tag = []
    if "mesh" in n:   tag.append(f"mesh{n['mesh']}")
    if "camera" in n: tag.append(f"CAM{n['camera']}")
    print("  " * d + f"- {name_of(i)} {'[' + ','.join(tag) + ']' if tag else ''}"
          + (f"  ({len(kids)} children)" if kids else ""))
    if d < maxd:
        for c in kids[:8]:
            walk(c, d + 1, maxd)
        if len(kids) > 8:
            print("  " * (d + 1) + f"… +{len(kids)-8} more")
for r in G["scenes"][0]["nodes"]:
    walk(r)

# ---------------------------------------------------------------- accessors
def read_accessor(ai):
    a = G["accessors"][ai]
    bv = G["bufferViews"][a["bufferView"]]
    base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    ncomp = {"SCALAR":1,"VEC2":2,"VEC3":3,"VEC4":4,"MAT4":16}[a["type"]]
    fmt = {5126:"f",5123:"H",5125:"I",5121:"B",5122:"h",5120:"b"}[a["componentType"]]
    size = struct.calcsize("<"+fmt)
    stride = bv.get("byteStride") or ncomp*size
    out = []
    for k in range(a["count"]):
        out.append(struct.unpack_from("<"+fmt*ncomp, BIN, base + k*stride))
    return out

# ---------------------------------------------------------------- camera paths
def quat_fwd(q):
    x, y, z, w = q
    # glTF camera looks down -Z
    return (-(2*(x*z + w*y)), -(2*(y*z - w*x)), -(1 - 2*(x*x + y*y)))

print("\n" + "=" * 78)
print("CAMERA PATHS")
for i, n in enumerate(NODES):
    if n.get("name", "").endswith("CameraPath"):
        kids = n.get("children", [])
        pts = []
        for c in kids:
            k = NODES[c]
            idx = int(re.sub(r"^_\d+_", "", k.get("name", "0")))
            pts.append((idx, k.get("translation", [0,0,0]), k.get("rotation", [0,0,0,1])))
        pts.sort()
        xs = [p[1][0] for p in pts]; ys = [p[1][1] for p in pts]; zs = [p[1][2] for p in pts]
        cx, cy, cz = sum(xs)/len(xs), sum(ys)/len(ys), sum(zs)/len(zs)
        radii = [math.hypot(p[1][0]-cx, p[1][2]-cz) for p in pts]
        angs  = [math.degrees(math.atan2(p[1][2]-cz, p[1][0]-cx)) % 360 for p in pts]
        steps = [((angs[k+1]-angs[k]) % 360) for k in range(len(angs)-1)]
        # does each node look at the pivot?
        errs = []
        for _, t, q in pts:
            fx, fy, fz = quat_fwd(q)
            tx, tz = cx - t[0], cz - t[2]
            L = math.hypot(tx, tz) or 1
            fL = math.hypot(fx, fz) or 1
            errs.append(math.degrees(math.acos(max(-1, min(1, (fx*tx + fz*tz)/(fL*L))))))
        print(f"\n  {n['name']}: {len(pts)} points, idx {pts[0][0]}..{pts[-1][0]}")
        print(f"    pivot        ({cx:.1f}, {cy:.1f}, {cz:.1f})")
        print(f"    radius       {min(radii):.2f} .. {max(radii):.2f}  (spread {max(radii)-min(radii):.2f})")
        print(f"    height Y     {min(ys):.3f} .. {max(ys):.3f}")
        print(f"    angle step   {min(steps):.3f}° .. {max(steps):.3f}°  (mean {sum(steps)/len(steps):.3f}°)")
        print(f"    total sweep  {sum(steps):.1f}°")
        print(f"    yaw-vs-pivot err {min(errs):.2f}° .. {max(errs):.2f}°")

print("\n" + "=" * 78)
print("CAMERAS")
for i, n in enumerate(NODES):
    if "camera" in n:
        cam = G["cameras"][n["camera"]]["perspective"]
        print(f"  {n['name']}: yfov={math.degrees(cam['yfov']):.2f}deg aspect={cam['aspectRatio']} "
              f"near={cam['znear']} far={cam['zfar']}")
        print(f"     T={[round(v,2) for v in n.get('translation',[0,0,0])]} "
              f"S={[round(v,4) for v in n.get('scale',[1,1,1])]}")

# ---------------------------------------------------------------- colliders
print("\n" + "=" * 78)
print("COLLIDERS")
apt = re.compile(r"^_(\d+)_(\d+)_\[(\d+)\]$")
rows, vcounts = [], []
for i, n in enumerate(NODES):
    m = apt.match(n.get("name", ""))
    if m and "mesh" in n:
        mesh = G["meshes"][n["mesh"]]
        prim = mesh["primitives"][0]
        nv = G["accessors"][prim["attributes"]["POSITION"]]["count"]
        ni = G["accessors"][prim["index"] if "index" in prim else prim["indices"]]["count"] if "indices" in prim else 0
        rows.append((int(m.group(1)), m.group(2), int(m.group(3)), nv, ni//3, path_of(i)))
        vcounts.append(nv)
rows.sort()
print(f"  {len(rows)} apartment colliders")
print(f"  verts/collider: min={min(vcounts)} max={max(vcounts)} mean={sum(vcounts)/len(vcounts):.1f}")
print(f"  {'idx':>4} {'unit':>6} {'[id]':>6} {'verts':>6} {'tris':>5}  parent")
for r in rows[:6] + rows[-4:]:
    print(f"  {r[0]:>4} {r[1]:>6} {r[2]:>6} {r[3]:>6} {r[4]:>5}  {r[5].split(' / ')[-2]}")

others = [n.get("name","") for n in NODES
          if "mesh" in n and not apt.match(n.get("name",""))]
print(f"\n  non-apartment meshes ({len(others)}):")
for o in others: print("   ", o)

# bracketed-id uniqueness -> is it an API id or a shared type id?
ids = Counter(r[2] for r in rows)
print(f"\n  bracketed [id]: {len(ids)} distinct across {len(rows)} units; "
      f"max repeat = {ids.most_common(1)[0][1]}  -> "
      f"{'NOT a unique key' if ids.most_common(1)[0][1] > 1 else 'unique key'}")
print("  id range:", min(ids), "..", max(ids))

# ---------------------------------------------------------------- bbox of one unit
print("\n" + "=" * 78)
print("SAMPLE COLLIDER GEOMETRY (unit 211)")
for i, n in enumerate(NODES):
    if n.get("name","").endswith("_211_[12]"):
        prim = G["meshes"][n["mesh"]]["primitives"][0]
        pos = read_accessor(prim["attributes"]["POSITION"])
        mn = [min(p[k] for p in pos) for k in range(3)]
        mx = [max(p[k] for p in pos) for k in range(3)]
        print(f"  node {n['name']}  T={[round(v,2) for v in n.get('translation',[0,0,0])]}")
        print(f"  local bbox min={[round(v,2) for v in mn]} max={[round(v,2) for v in mx]}")
        print(f"  local size   ={[round(mx[k]-mn[k],2) for k in range(3)]}")
        print(f"  verts={len(pos)} attrs={list(prim['attributes'])}")
        break
