#!/usr/bin/env python3
"""Proper 'which frame best shows this apartment?' solver.

Scores every (apartment, frame) pair with the real baked camera transform:
  - is the centroid inside the frustum, and how central is it
  - does the collider's outward normal face the camera
This is the computation you want OFFLINE to power 'click a unit -> spin the
building to where you can see it'. Also used here to re-test the [n] suffix.
"""
import json, struct, math, re, sys, statistics
from collections import defaultdict

PATH = sys.argv[1] if len(sys.argv) > 1 else "../assets/scene10.glb"
blob = open(PATH, "rb").read()
off, chunks, total = 12, {}, struct.unpack_from("<III", blob, 0)[2]
while off < total:
    cl, ct = struct.unpack_from("<II", blob, off)
    chunks[ct] = blob[off+8:off+8+cl]; off += 8+cl+(-cl % 4)
G = json.loads(chunks[0x4E4F534A].decode()); BIN = chunks[0x004E4942]
N = G["nodes"]

def mat_of(n):
    if "matrix" in n:
        m = n["matrix"]; return [m[0:4], m[4:8], m[8:12], m[12:16]]
    t = n.get("translation",[0,0,0]); q = n.get("rotation",[0,0,0,1]); s = n.get("scale",[1,1,1])
    x,y,z,w = q
    R = [[1-2*(y*y+z*z), 2*(x*y-w*z), 2*(x*z+w*y)],
         [2*(x*y+w*z), 1-2*(x*x+z*z), 2*(y*z-w*x)],
         [2*(x*z-w*y), 2*(y*z+w*x), 1-2*(x*x+y*y)]]
    return [[R[0][0]*s[0],R[1][0]*s[0],R[2][0]*s[0],0],
            [R[0][1]*s[1],R[1][1]*s[1],R[2][1]*s[1],0],
            [R[0][2]*s[2],R[1][2]*s[2],R[2][2]*s[2],0],
            [t[0],t[1],t[2],1]]
def mul(a,b): return [[sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
def xf(m,p): return [sum(p[k]*m[k][i] for k in range(3))+m[3][i] for i in range(3)]
def xf3(m,p): return [sum(p[k]*m[k][i] for k in range(3)) for i in range(3)]

par = {}
for i,n in enumerate(N):
    for c in n.get("children",[]): par[c]=i
def world(i):
    ch=[]
    while i is not None: ch.append(i); i=par.get(i)
    M=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
    for j in reversed(ch): M=mul(mat_of(N[j]),M)
    return M
def acc(ai, comps=3):
    a=G["accessors"][ai]; bv=G["bufferViews"][a["bufferView"]]
    base=bv.get("byteOffset",0)+a.get("byteOffset",0); st=bv.get("byteStride") or 4*comps
    f="<"+"f"*comps
    return [struct.unpack_from(f,BIN,base+k*st) for k in range(a["count"])]

# ---- camera path A: world position + basis per frame ----------------------
cp = next(i for i,n in enumerate(N) if n.get("name")=="_73_CameraPath")
frames={}
for c in N[cp]["children"]:
    idx=int(re.sub(r"^_\d+_","",N[c]["name"])); W=world(c)
    pos=[W[3][0],W[3][1],W[3][2]]
    # normalize basis (strip the 0.01 scale)
    def nz(v):
        L=math.sqrt(sum(t*t for t in v)) or 1; return [t/L for t in v]
    right=nz([W[0][0],W[0][1],W[0][2]]); up=nz([W[1][0],W[1][1],W[1][2]])
    back =nz([W[2][0],W[2][1],W[2][2]])          # glTF: camera looks down -Z
    frames[idx]=(pos,right,up,[-back[0],-back[1],-back[2]])

YFOV=math.radians(60.01); ASPECT=16/9
TANY=math.tan(YFOV/2); TANX=TANY*ASPECT

apt=re.compile(r"^_(\d+)_(\d+)_\[(\d+)\]$")
units={}
for i,n in enumerate(N):
    m=apt.match(n.get("name",""))
    if not(m and "mesh" in n): continue
    prim=G["meshes"][n["mesh"]]["primitives"][0]
    P=acc(prim["attributes"]["POSITION"]); NR=acc(prim["attributes"]["NORMAL"])
    W=world(i)
    wp=[xf(W,p) for p in P]; wn=[xf3(W,q) for q in NR]
    c=[sum(p[k] for p in wp)/len(wp) for k in range(3)]
    units[m.group(2)]=(int(m.group(3)), c, wp, wn)

def score(c, wp, wn, f):
    pos,right,up,fwd=frames[f]
    d=[c[k]-pos[k] for k in range(3)]
    z=sum(d[k]*fwd[k] for k in range(3))
    if z<=0: return -9e9
    x=sum(d[k]*right[k] for k in range(3)); y=sum(d[k]*up[k] for k in range(3))
    ndx=abs(x/(z*TANX)); ndy=abs(y/(z*TANY))
    if ndx>1 or ndy>1: return -9e9                       # outside frustum
    # facing: area-weighted normals pointing back at camera
    v=[-d[0],-d[1],-d[2]]; L=math.sqrt(sum(t*t for t in v)) or 1; v=[t/L for t in v]
    face=sum(max(0,sum(n[k]*v[k] for k in range(3))) for n in wn)/len(wn)
    return face*2.0 + (1-ndx)*0.5 + (1-ndy)*0.2

rows=[]
for u,(br,c,wp,wn) in units.items():
    best=max(frames, key=lambda f: score(c,wp,wn,f))
    d=min(abs(br-best),120-abs(br-best))
    rows.append((u,br,best,d))
rows.sort()

print(f"{'unit':>6} {'[n]':>5} {'best':>5} {'delta':>6}")
for r in rows[:14]: print(f"{r[0]:>6} {r[1]:>5} {r[2]:>5} {r[3]:>6}")
ds=[r[3] for r in rows]
print(f"\nn={len(ds)} mean|delta|={statistics.mean(ds):.1f} median={statistics.median(ds)} max={max(ds)}")
w=sum(1 for d in ds if d<=6)
print(f"within +/-6 frames: {w}/{len(ds)} = {100*w/len(ds):.0f}%  (random ~11%)")
print("\nVERDICT:", "[n] IS the best-view frame" if 100*w/len(ds)>50 else
      "[n] is NOT a frame index -- treat it as opaque; unit number is the join key")

# emit the useful artifact regardless
out={u:{"bestFrame":b,"bracket":br} for u,br,b,_ in rows}
json.dump(out, open("../assets/data/best_frame_by_unit.json","w"), indent=1)
print(f"\nwrote best_frame_by_unit.json ({len(out)} units) <- bake this at build time")
