# Exterior building view — how it's built

Teardown of the Groove Residences viewer (`allinone.prod.resimo.io`, vendor: Resimo/Yslab),
plus a working reference implementation, for building the same thing for a real-estate client.

Everything below is measured from the live assets, not inferred.

---

## 1. The technique

It is **not** a real-time 3D building. It's a pre-rendered turntable with an
invisible 3D scene locked to it.

```
  ┌─ 120 offline-rendered stills (AVIF)  ← what the user sees
  └─ 120-node camera path + collider meshes (glTF)  ← what the user clicks
        ▲ same index, same camera, same frame
```

Drag scrubs the image sequence. In lockstep, a transparent WebGL canvas sets its
camera to the *same-numbered* node of a camera path baked into the glTF — the very
camera that rendered that still in Blender. Raycasting against invisible collider
volumes therefore lands pixel-accurately on the photo.

You get path-traced archviz quality at 60fps on a phone, plus exact per-apartment
hit-testing. Neither is achievable with real-time rendering at this fidelity.

**Verified in `index.html`** — toggle "show colliders" and rotate: the
wireframes stay welded to the rendered balconies at every angle.

---

## 2. Measured spec of the production system

### Frame sequences
```
animations7/{scene}/{day|night}/{1440|3840}/{0..119}.avif
animations7/{scene}/{day|night}/spritesheet.avif
animations7/{scene}/{day}/Data/{scene}.json   →  {animationName, fps:17, scaledBuildings:[]}
```
| | |
|---|---|
| Frames per orbit | **120** (index 120 → 404) — 3.0°/frame, full 360° |
| Resolutions | 1440×810 (~195 KB) · 3840×2160 (~1.4 MB) |
| Variants | `day` and `night`, separate full sequences |
| Alpha | **none** — flat opaque RGB. No sky/building compositing |
| Scrub proxy | one 3200×2160 spritesheet = 10×12 grid of 320×180 tiles, 408 KB |
| Playback | fps 17 for auto-spin |
| Scenes | `A` (close orbit, r≈113, h≈36) and `AppView` (masterplan, r≈480, h≈150) |

### `scene10.glb` — 418 KB, and it contains no visible geometry
Blender glTF I/O v3.5.30 · 618 nodes · 70 meshes · **2 materials, both named
`01_Colliders_[MainCollider]`** · 3 cameras · 0 animations.

```
JeffExport
├── _0_Group_A
│   ├── _194_Tooltip
│   ├── _195_Camera_A            ← 60.01° yfov, 16:9, near .3 far 6000
│   ├── _1_Building_Colliders    ← SM7 massing + SM7F0 (2 meshes)
│   ├── _4_Apartment_Colliders   ← 68 meshes, "_55_211_[12]"
│   └── _73_CameraPath           ← 120 children "0".."119", pos + quat each
├── _196_Compass                 ← defines north for the compass widget
├── _197_AppView
│   ├── _198_CameraPath          ← 120 children
│   └── _319_Camera_AppView
├── _320_Main_Camera             ← free-orbit cam for the apartment 3D view
├── _321_WalkMarkers             ← 277 spheres (apartment-tour positions)
└── _599_Amenities               ← 17 POIs, "1_Amenities_SM7-InfinityPool"
```

Camera path geometry (measured):

| | orbit A | AppView |
|---|---|---|
| points | 120 | 120 |
| height Y | 35.581 (constant) | 149.981 (constant) |
| radius | 112.65 – 114.55 | 476.40 – 484.41 |
| angular step | 3.025° (uniform) | 3.025° |
| camera aim vs pivot | 0.00–0.48° | 9.45–10.41° |

Two consequences worth acting on:

- **Radius wobbles ~1.7% and AppView is aimed ~10° off its own pivot.** The paths
  are hand-adjusted, not mathematically circular. You cannot reconstruct the camera
  analytically — **bake every frame's position and rotation** and ship them.
- Colliders are **extruded apartment footprints**, not boxes: 24–150 verts each
  (mean 64), e.g. unit 211 is 76 verts, 27.8 × 4.1 × 18.4 units. That's why picking
  follows curved balconies. Duplexes are a single collider spanning two floors.

### Data
- Inventory: `api.resimo.pl/.../investment/749/apartments/` → `[{number:"SM07", apartments:[…]}]`,
  68 records: `id, name, mappingName, buildingNumber, area, rooms, status,
  additionalElements{room, view, floor, internalAreaSqm}`.
- **Join key is the unit number parsed from the collider node name — 68/68 exact match.**
- The bracketed `[12]` in `_55_211_[12]` is **opaque**. Tested and rejected: not a
  unique id (42 distinct across 68, repeats ×6), not a layout type (units sharing it
  have different areas/rooms), and not a best-view frame index (mean error 21.7
  frames vs 11% random baseline — see `proto/best_frame.py`). Don't design around it.
- Four hosts — app shell, `jeff.cdn` (renders + glb), `apartments-miniatury.cdn`
  (floorplans), `api.resimo.pl` (inventory) — so renders, plans and stock version
  independently. Every asset carries `?v=10`.

---

## 3. Production pipeline

**Blender is 80% of the job. The web app is the easy part.**

1. **Model + light** the exterior once, day and night lighting setups.
2. **Camera on a circular path**, 120 keyframes, locked height. Frame it so the
   building never clips at any angle — you can't fix framing later without a re-render.
3. **Render 120 stills × 2 times of day at 3840×2160.** Downscale to 1440×810.
   Encode AVIF (~q50 gives the 195 KB / 1.4 MB above). Build the spritesheet.
4. **Author a collider collection**: extrude each apartment footprint from the floor
   plans, plus a building massing shell and amenity markers. Name them
   `{unit}_[{whatever}]` — the unit number is the contract with your inventory system.
5. **Bake the camera path**: sample the render camera at each of the 120 frames into
   empties parented under a `CameraPath` node, named `0`…`119`.
6. **Export colliders + camera + path as one GLB** from the *same scene*, untouched.
   Any transform drift here and every click target slides off the building.
7. **Validate in CI**: every collider name resolves to a live unit, every unit has a
   collider, frame count == camera path child count. This check catches the failure
   mode that is otherwise invisible until a customer clicks the wrong flat.

### Budget
| | |
|---|---|
| Renders | 240 frames @ 4K. ~20 min/frame → ~80 node-hours; ~8h on a 10-node farm |
| Storage | ~400 MB per scene (4K + 1440 + sprites, day + night) |
| Typical session | sprite 0.4 MB + ~30 frames @1440 (~6 MB) + a few 4K (~5 MB) ≈ **10–15 MB** |
| Re-render cost | any facade change = all 240 frames again. Lock design before rendering |

Frame count: 120 (3°/step) is the right default. Below ~72 the rotation reads as
steppy; 180 is silky but 50% more render and storage.

---

## 4. Runtime — what actually matters

Full implementation in [`index.html`](index.html) (~300 lines, three.js).
The core is genuinely this small:

```js
function applyFrame() {
  plate.draw(bitmaps[night ? 'night' : 'day'][frame]);  // the still
  pathNodes[frame].getWorldPosition(camera.position);   // the baked camera
  pathNodes[frame].getWorldQuaternion(camera.quaternion);
}
```

**Aspect-ratio registration.** The plate is 16:9; browser windows are not. Draw the
plate `cover` and correct the camera, or your hit targets drift as the window resizes:

```js
camera.aspect = av;
camera.fov = av > 16/9
  ? 2*Math.atan(Math.tan(rad(YFOV)/2) * (16/9)/av) * 180/Math.PI   // wide: crop top/bottom
  : YFOV;                                                          // tall: crop sides
```

**Loading ladder.** Spritesheet (1 request, whole orbit scrubbable) → 1440 sequence
decoded outward from the current frame → a single 4K frame ~150 ms after the drag
settles. Decode via `createImageBitmap` off-thread into a ring buffer; swapping
`<img>.src` at 17fps janks badly because AVIF decode is not cheap.

**Highlighting.** Render every collider depth-only (`colorWrite:false`), then draw the
selected one again with `depthFunc: LessEqualDepth` — it occludes correctly against
the rest of the building for free.

**Labels.** Use the collider's averaged outward normal vs the view direction. A
per-label raycast is ~4.6k intersection tests per frame and destroys the scrub;
the dot product is O(1) and gives the same answer since every unit sits on the skin.

### Gotchas that cost time here
- **three.js strips `[` `]` `.` `:` `/` from glTF node names.** `_55_211_[12]` arrives
  as `_55_211_12`. My first run silently found 0 colliders and painted the raw opaque
  collider material over the render. Match both forms.
- **Never bind the drag gesture to an element that contains your UI.** Binding
  pointerdown to the stage wrapper meant a press on a button bubbled up and hit
  `setPointerCapture`, which retargets the rest of the gesture *and the synthesised
  click* to the capturing element — so every button was dead. Bind to the canvas,
  which is a sibling of the control bar. The tell is diagnostic: **buttons dead under
  a mouse but working under touch emulation**, because touch synthesises its click by
  a different path that capture doesn't intercept. Overlays that shouldn't eat input
  (`#labels`, `#hud`, `#card`, the progress bar) all need `pointer-events:none`.
- Debug wireframes need `depthTest:false` or the massing collider swallows them.
  Side effect: far-side colliders then draw through the building, which is expected.
- Colliders ship with a real material — always reassign it, or you get a black blob.

---

## 5. What's in this folder

```
assets/    scene10.glb, 120 day + 120 night frames, spritesheets, inventory JSON  (38 MB)
proto/
  viewer.html        working reference implementation — drag, pick, labels, day/night
  inspect_glb.py     dissects the GLB: hierarchy, camera paths, collider stats
  verify_bracket.py  tests (and rejects) the "[n] is a frame index" hypothesis
  best_frame.py      frustum+facing solver → best_frame_by_unit.json (spin-to-unit)
```

Run it:

```bash
python3 -m http.server 8912 --directory claude
```

then open `http://localhost:8912/`.

The downloaded renders are Resimo/JMJ's own artwork, kept here only to prove the
mechanism — your build replaces them with your client's renders from step 3.
