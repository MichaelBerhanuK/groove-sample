#!/usr/bin/env python3
"""Hypothesis: the [n] suffix on each apartment collider is the ORBIT FRAME
at which that apartment best faces the camera -- i.e. 'select unit -> spin
the building to the angle where you can see it'.

Test: compute each collider's world azimuth around the A-path pivot, find the
frame whose camera sits at that azimuth, compare to the bracketed number.
"""
import json, struct, math, re, sys
from collections import Counter

PATH = sys.argv[1] if len(sys.argv) > 1 else "../assets/scene10.glb"
blob = open(PATH, "rb").read()
off, chunks, total = 12, {}, struct.unpack_from("<III", blob, 0)[2]
while off < total:
    clen, ctype = struct.unpack_from("<II", blob, off)
    chunks[ctype] = blob[off+8: off+8+clen]; off += 8 + clen + (-clen % 4)
G = json.loads(chunks[0x4E4F534A].decode()); BIN = chunks[0x004E4942]
NODES = G["nodes"]

# ---- matrix helpers -------------------------------------------------------
def mat_of(n):
    if "matrix" in n:
        m = n["matrix"]; return [m[0:4], m[4:8], m[8:12], m[12:16]]  # column-major
    t = n.get("translation", [0,0,0]); q = n.get("rotation", [0,0,0,1]); s = n.get("scale",[1,1,1])
    x,y,z,w = q
    R = [[1-2*(y*y+z*z), 2*(x*y-w*z),   2*(x*z+w*y)],
         [2*(x*y+w*z),   1-2*(x*x+z*z), 2*(y*z-w*x)],
         [2*(x*z-w*y),   2*(y*z+w*x),   1-2*(x*x+y*y)]]
    return [[R[0][0]*s[0], R[1][0]*s[0], R[2][0]*s[0], 0],
            [R[0][1]*s[1], R[1][1]*s[1], R[2][1]*s[1], 0],
            [R[0][2]*s[2], R[1][2]*s[2], R[2][2]*s[2], 0],
            [t[0], t[1], t[2], 1]]

def mul(a, b):  # a then b  (column-major, v*a*b)
    return [[sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]

def xform(m, p):
    return [sum(p[k]*m[k][i] for k in range(3)) + m[3][i] for i in range(3)]

parent = {}
for i, n in enumerate(NODES):
    for c in n.get("children", []): parent[c] = i

def world(i):
    chain = []
    while i is not None:
        chain.append(i); i = parent.get(i)
    M = [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
    for j in reversed(chain): M = mul(mat_of(NODES[j]), M)
    return M

def read_pos(ai):
    a = G["accessors"][ai]; bv = G["bufferViews"][a["bufferView"]]
    base = bv.get("byteOffset",0) + a.get("byteOffset",0)
    stride = bv.get("byteStride") or 12
    return [struct.unpack_from("<fff", BIN, base + k*stride) for k in range(a["count"])]

# ---- camera path A --------------------------------------------------------
cp = next(i for i,n in enumerate(NODES) if n.get("name") == "_73_CameraPath")
pts = []
for c in NODES[cp]["children"]:
    k = NODES[c]; idx = int(re.sub(r"^_\d+_", "", k["name"]))
    w = world(c); pts.append((idx, [w[3][0], w[3][1], w[3][2]]))
pts.sort()
cx = sum(p[1][0] for p in pts)/len(pts); cz = sum(p[1][2] for p in pts)/len(pts)
cam_az = {i: math.degrees(math.atan2(p[2]-cz, p[0]-cx)) % 360 for i, p in pts}

print(f"pivot (x,z) = ({cx:.1f}, {cz:.1f})   frames = {len(pts)}")
print(f"frame 0 azimuth = {cam_az[0]:.2f}deg, frame 1 = {cam_az[1]:.2f}deg, "
      f"step = {(cam_az[1]-cam_az[0])%360 - 360:.3f}deg\n")

# ---- apartments -----------------------------------------------------------
apt = re.compile(r"^_(\d+)_(\d+)_\[(\d+)\]$")
rows = []
for i, n in enumerate(NODES):
    m = apt.match(n.get("name",""))
    if not (m and "mesh" in n): continue
    prim = G["meshes"][n["mesh"]]["primitives"][0]
    pos = read_pos(prim["attributes"]["POSITION"])
    W = world(i)
    wp = [xform(W, p) for p in pos]
    ccx = sum(p[0] for p in wp)/len(wp); ccy = sum(p[1] for p in wp)/len(wp); ccz = sum(p[2] for p in wp)/len(wp)
    az = math.degrees(math.atan2(ccz - cz, ccx - cx)) % 360
    # frame whose camera azimuth is nearest the apartment's outward azimuth
    best = min(cam_az, key=lambda f: min(abs(cam_az[f]-az), 360-abs(cam_az[f]-az)))
    rows.append((m.group(2), int(m.group(3)), best, az, (ccx,ccy,ccz)))

rows.sort(key=lambda r: r[0])
diffs = []
for unit, bracket, best, az, c in rows:
    d = min(abs(bracket-best), 120-abs(bracket-best))
    diffs.append(d)

print(f"{'unit':>6} {'[n]':>5} {'predicted':>9} {'delta':>6}  {'azimuth':>8}  centroid")
for (unit, bracket, best, az, c), d in list(zip(rows, diffs))[:16]:
    print(f"{unit:>6} {bracket:>5} {best:>9} {d:>6}  {az:>8.1f}  ({c[0]:.0f},{c[1]:.0f},{c[2]:.0f})")

import statistics
print(f"\nn={len(diffs)}  mean|delta|={statistics.mean(diffs):.2f} frames  "
      f"median={statistics.median(diffs)}  max={max(diffs)}")
within = sum(1 for d in diffs if d <= 6)
print(f"within +/-6 frames (+/-18deg): {within}/{len(diffs)} = {100*within/len(diffs):.0f}%")
print(f"random baseline would be ~{100*13/120:.0f}%")
