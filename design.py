"""MPCNC Burly (J, 25.4 mm tube) - full assembly from V1 Engineering's own parts.

Printed parts are V1's Burly J STLs (thingiverse.com/thing:1671517, CC BY-NC-SA 4.0),
decimated to a 0.35 mm grid and stored as mesh_<part>.json. Each part is placed from its
own geometry - tube seats, bearing bolt holes and mating faces measured from the STLs (see
README.md) - and checked against V1's assembly photos. Tube lengths follow V1's Burly cut
list (burly_calc.py).

World frame: X right, Y back, Z up, table top at Z=0, 0,0 corner front-left.
"""
import base64
import json
import math
import zlib
from array import array
from pathlib import Path

import build123d as bd
from OCP.BRep import BRep_Builder
from OCP.gp import gp_Dir, gp_Pnt
from OCP.Poly import Poly_Triangle, Poly_Triangulation
from OCP.TopoDS import TopoDS_Face

from burly_calc import cut_list, load_params

P = load_params()
C = cut_list(P)
HERE = Path(__file__).parent
S2 = math.sqrt(0.5)

COL = {k: bd.Color(*v) for k, v in P["colors"].items()}
STEEL = bd.Color(0.72, 0.74, 0.77)
MOTOR = bd.Color(0.08, 0.08, 0.08)
BRASS = bd.Color(0.80, 0.62, 0.25)
TABLE = bd.Color(0.76, 0.62, 0.42)
WORK = bd.Color(0.55, 0.85, 0.55)   # opaque: keep every material opaque in the Tertius viewer

# ---- rigid transforms: (R rows, t), p' = R p + t -------------------------


def frame(cols, local, world):
    """Transform whose rotation has the given column images and maps point `local` to `world`."""
    R = [[cols[c][r] for c in range(3)] for r in range(3)]
    Rl = [sum(R[r][k] * local[k] for k in range(3)) for r in range(3)]
    return R, [world[r] - Rl[r] for r in range(3)]


def compose(a, b):
    """a after b."""
    Ra, ta = a
    Rb, tb = b
    R = [[sum(Ra[r][k] * Rb[k][c] for k in range(3)) for c in range(3)] for r in range(3)]
    t = [sum(Ra[r][k] * tb[k] for k in range(3)) + ta[r] for r in range(3)]
    return R, t


def apply(T, p):
    R, t = T
    return [sum(R[r][k] * p[k] for k in range(3)) + t[r] for r in range(3)]


def det(R):
    return (R[0][0] * (R[1][1] * R[2][2] - R[1][2] * R[2][1])
            - R[0][1] * (R[1][0] * R[2][2] - R[1][2] * R[2][0])
            + R[0][2] * (R[1][0] * R[2][1] - R[1][1] * R[2][0]))


def rot_z(deg, about_local, to_world, dz=0.0):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return frame([(c, s, 0), (-s, c, 0), (0, 0, 1)], (*about_local, 0), (*to_world, dz))


# ---- meshes ---------------------------------------------------------------
_mesh_cache, _array_cache = {}, {}


def _arrays(name):
    """Vertices (mm, flat list) and triangle indices of mesh_<name>.json (meshpack format)."""
    if name not in _array_cache:
        doc = json.loads((HERE / f"mesh_{name}.json").read_text())
        q = array("h")
        q.frombytes(zlib.decompress(base64.b64decode(doc["v"])))
        o, s = doc["origin"], doc["q"]
        v = [q[i] * s + o[i % 3] for i in range(len(q))]
        f = array(doc["itype"])
        f.frombytes(zlib.decompress(base64.b64decode(doc["f"])))
        _array_cache[name] = (v, f)
    return _array_cache[name]


def mesh(name, mirror=False):
    """V1 part as a build123d face carrying its triangulation; `mirror` reflects it in X
    (V1's 'Mirrored' parts). Normals are smooth but creased at edges sharper than 35 deg,
    so every part exports with NORMALs like the B-rep parts do - the Tertius viewer merges
    all meshes into one geometry and drops it if some lack normals."""
    key = (name, mirror)
    if key not in _mesh_cache:
        v, f = _arrays(name)
        sx = -1.0 if mirror else 1.0
        n = len(f) // 3
        tris, tnorm = [], []
        for t in range(n):
            a, b, c = f[3 * t], f[3 * t + 1], f[3 * t + 2]
            if mirror:
                b, c = c, b
            pa = (sx * v[3 * a], v[3 * a + 1], v[3 * a + 2])
            pb = (sx * v[3 * b], v[3 * b + 1], v[3 * b + 2])
            pc = (sx * v[3 * c], v[3 * c + 1], v[3 * c + 2])
            e1 = [pb[k] - pa[k] for k in range(3)]
            e2 = [pc[k] - pa[k] for k in range(3)]
            cr = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]]
            ln = math.sqrt(cr[0] ** 2 + cr[1] ** 2 + cr[2] ** 2)
            if ln == 0:
                continue
            tris.append((a, b, c))
            tnorm.append((cr[0] / ln, cr[1] / ln, cr[2] / ln, ln))
        # smoothing groups per vertex: (accumulated normal, first normal, node id)
        groups = {}
        nodes, normals, out = [], [], []
        for t, (a, b, c) in enumerate(tris):
            nx, ny, nz, w = tnorm[t]
            ids = []
            for vi in (a, b, c):
                for g in groups.setdefault(vi, []):
                    if g[1][0] * nx + g[1][1] * ny + g[1][2] * nz > 0.82:
                        g[0][0] += nx * w
                        g[0][1] += ny * w
                        g[0][2] += nz * w
                        ids.append(g[2])
                        break
                else:
                    g = [[nx * w, ny * w, nz * w], (nx, ny, nz), len(nodes)]
                    groups[vi].append(g)
                    nodes.append((sx * v[3 * vi], v[3 * vi + 1], v[3 * vi + 2]))
                    normals.append(g[0])
                    ids.append(g[2])
            out.append(ids)
        tri = Poly_Triangulation(len(nodes), len(out), False, True)
        for i, (p, nv) in enumerate(zip(nodes, normals)):
            tri.SetNode(i + 1, gp_Pnt(*p))
            ln = math.sqrt(nv[0] ** 2 + nv[1] ** 2 + nv[2] ** 2) or 1.0
            tri.SetNormal(i + 1, gp_Dir(nv[0] / ln, nv[1] / ln, nv[2] / ln))
        for i, (a, b, c) in enumerate(out):
            tri.SetTriangle(i + 1, Poly_Triangle(a + 1, b + 1, c + 1))
        face = TopoDS_Face()
        BRep_Builder().MakeFace(face, tri)
        _mesh_cache[key] = bd.Face(face)
    return _mesh_cache[key]


def mesh_bounds(name, T):
    """World bounding box of a placed part, from its vertices."""
    v, _ = _arrays(name)
    lo, hi = [1e9] * 3, [-1e9] * 3
    for i in range(0, len(v), 3):
        p = apply(T, (v[i], v[i + 1], v[i + 2]))
        for k in range(3):
            lo[k] = min(lo[k], p[k])
            hi[k] = max(hi[k], p[k])
    return lo, hi


def part(name, T, label, color):
    """Place V1 part `name` with transform T (improper T uses the mirrored mesh)."""
    R, t = T
    mirror = det(R) < 0
    if mirror:   # fold the reflection into the mesh, keep a proper rotation
        R = [[-R[r][0], R[r][1], R[r][2]] for r in range(3)]
    plane = bd.Plane(origin=tuple(t), x_dir=(R[0][0], R[1][0], R[2][0]), z_dir=(R[0][2], R[1][2], R[2][2]))
    s = mesh(name, mirror).moved(bd.Location(plane))
    s.label = label
    s.color = color
    return s


def tube(length, label, at, axis="Z", color=STEEL, od=None, wall=None):
    r = (od or P["tube_od"]) / 2
    w = wall or P["tube_wall"]
    t = bd.Cylinder(r, length) - bd.Cylinder(r - w, length)
    rot = {"X": (0, 90, 0), "Y": (90, 0, 0), "Z": (0, 0, 0)}[axis]
    t = t.moved(bd.Location(tuple(at), rot))
    t.label = label
    t.color = color
    return t


def box(size, centre, label, color):
    b = bd.Box(*size).moved(bd.Location(tuple(centre)))
    b.label = label
    b.color = color
    return b


def rod(d, length, base, label, color):
    c = bd.Cylinder(d / 2, length, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
    c = c.moved(bd.Location(tuple(base)))
    c.label = label
    c.color = color
    return c



A, B = COL["A"], COL["B"]
NEMA = 42.3, 40.0
I3 = [(1, 0, 0), (0, 1, 0), (0, 0, 1)]
MIRROR_X = ([[-1, 0, 0], [0, 1, 0], [0, 0, 1]], [0, 0, 0])
MIRROR_Y = ([[1, 0, 0], [0, -1, 0], [0, 0, 1]], [0, 0, 0])


def at(x, y, z=0.0):
    return ([[1, 0, 0], [0, 1, 0], [0, 0, 1]], [x, y, z])


def label_m(name, T):
    return name + (" M" if det(T[0]) < 0 else "")


def nema(centre, shaft_axis, label):
    s = {"X": (NEMA[1], NEMA[0], NEMA[0]), "Y": (NEMA[0], NEMA[1], NEMA[0]), "Z": (NEMA[0], NEMA[0], NEMA[1])}
    return box(s[shaft_axis], centre, label, MOTOR)


# ---- measured part geometry (V1 STL coordinates, mm) -----------------------
# Lock Corner: cup on the leg top, bore (104.99, 129.77) along Zp, floor Zp 0-7 (the leg stops at 7).
# Bottom Corner: rail U along Zp at (110, 105.06) r 12.88, opening -Yp; back face Yp 128 glued to the
#   lock floor; lock screw on (Xp 110, Zp 23.5); flange face Yp 92.1, M4 square 38.8 about (110, 23.5).
# Top Corner: rail U along Zp at (138.5, 107.07), flange face Yp 94.07, M4 square about (138.5, 23.5).
#   U centre - flange = 12.96 + 13.0, so the corner halves sit 1.54 apart when the spacer sets 27.5.
# Spacer Corner: saddles along Zp at (Xp 11.7, Yp 0) and along Xp at (Yp 27.5, Zp 11.7).
# Foot: leg bore (102.5, 102.5) open to the table; the leg is clamped at any height in it.
# Roller: rail along Zp at (90.18, 110) - two bearings on M8 bolts along Yp at (Xp 113.88, Zp 9.1 /
#   65.9) ride its top; gantry saddle along Yp at (Xp 128.45, Zp 37.5) r 13.05 -> tube centre Xp 128.1.
# RollerMount: gantry bore along Zp at (67.5, 80.22); screws at Xp 40.58 / 94.45, Zp 35.3 into the
#   roller's holes at (Yp 118.12, Zp 10.9 / 64.11); NEMA17 boss (67.5, 124.69), motor face Zp 6.
# XYZ: Z rail pockets (66.77 / 138.23, 86.33), T8 nut (102.5, 110.51), centre-back hole (102.5,
#   127.01) through a flange Zp 0-6.5, side holes (49.51 / 155.49, 103.53); symmetric about
#   Xp 102.5, opening (front) toward -Yp.
# Gantry Spacer: 23.03 tall on bolt B at (102.5, 97.59).
# XY: gantry tube along Zp at (116.25, 107.2) on bearings at Yp 83.5; bolt B along Xp at
#   (Yp 71.83, Zp 78.16) through a boss Xp 102.6-129.6, so the tube sits 35.37 from bolt B.
# Z Motor / Z Lower: rails (66.77 / 138.23, 153.65 resp. 114.79), leadscrew 24.18 in front of them.
# Tool Mount: rail cups (66.77 / 138.23, 91.49), front face Yp 72.5; screws 22.5 and 97.5 up.
# Nut Trap: nuts at Xp 69.5 / 144.5, the Xp 47 end flush with the Z rail bottom.
U_SAG = 0.18
LOCK_FLOOR = 7.0
RAIL_STACK = 27.5
GANTRY_ABOVE_RAIL = 128.1 - 90.18
ROLLER_RAIL = (90.18, 110.0, 37.5)
XYZ_B = (102.5, 127.01)
Z_RAILS_M = ((66.77, 86.33), (138.23, 86.33))
LEAD_M = (102.5, 110.51)
TOOL_FACE_M = (102.5, 86.33 - (91.49 - 72.5))

# ---- base -----------------------------------------------------------------
lx = (C["x_rail"] - 47) / 2          # leg / rail lines; the corners are 47 long along each rail
ly = (C["y_rail"] - 47) / 2
leg = C["leg"]
# Measured on the machine: leg length and the height of the lower rails' underside. The legs are
# set in the feet with a block, so the leg bottom sits leg_lift above the table.
R_TUBE = P["tube_od"] / 2
z_lr = P["lower_rail_bottom"] + R_TUBE               # Y rails (lower)
z_lt = z_lr - (128 - 105.06) + U_SAG                 # lock floor top = bottom corner back
leg_lift = z_lt - LOCK_FLOOR - leg
assert 0 <= leg_lift <= 25, f"leg bottom {leg_lift:.1f} mm above the table - check leg / lower_rail_bottom"
z_ur = z_lr + RAIL_STACK                             # X rails (upper)
z_gx = z_lr + GANTRY_ABOVE_RAIL                      # X gantry tube, carried along the Y rails
z_gy = z_ur + GANTRY_ABOVE_RAIL

# Corner parts placed for the front-left corner at the origin; the others are mirrors of it
# (two plain, two mirrored, as V1 ships them).
T_foot = frame(I3, (102.5, 102.5, 0), (0, 0, 0))
T_lock = frame([(1, 0, 0), (0, -1, 0), (0, 0, -1)], (104.99, 129.77, 0), (0, 0, z_lt))
T_bot = frame([(1, 0, 0), (0, 0, -1), (0, 1, 0)], (110, 128, 23.5), (0, 0, z_lt))
T_spc = frame([(1, 0, 0), (0, 0, 1), (0, -1, 0)], (11.7, 0, 11.7), (0, 0, z_lr))
T_top = frame([(0, 1, 0), (0, 0, 1), (1, 0, 0)], (138.5, 94.07, 23.5), (0, 0, z_ur + U_SAG - 13.0))

corners = []
for i, (sx, sy) in enumerate([(-1, -1), (1, -1), (1, 1), (-1, 1)]):
    M = at(0, 0)
    if sx > 0:
        M = compose(MIRROR_X, M)
    if sy > 0:
        M = compose(MIRROR_Y, M)
    place = compose(at(sx * lx, sy * ly), M)
    Tl, Tb, Ts, Tt = (compose(place, T) for T in (T_lock, T_bot, T_spc, T_top))
    corners.append(bd.Compound(label=f"Corner {i + 1}", children=[
        part("foot", compose(at(sx * lx, sy * ly), T_foot), "Foot", A),
        tube(leg, "Leg", (sx * lx, sy * ly, leg_lift + leg / 2)),
        part("lock_corner", Tl, label_m("Lock Corner", Tl), A),
        part("bottom_corner", Tb, label_m("Bottom Corner", Tb), B),
        part("spacer_corner", Ts, "Spacer Corner", A),
        part("top_corner", Tt, label_m("Top Corner", Tt), B),
    ]))

rails = [tube(C["y_rail"], f"Y rail {'L' if s < 0 else 'R'}", (s * lx, 0, z_lr), "Y") for s in (-1, 1)]
rails += [tube(C["x_rail"], f"X rail {'F' if s < 0 else 'B'}", (0, s * ly, z_ur), "X") for s in (-1, 1)]

# ---- rollers: the two Y-rail rollers carry the X gantry, the X-rail rollers the Y gantry ----
T_roll_y = frame([(0, 0, 1), (1, 0, 0), (0, 1, 0)], ROLLER_RAIL, (-lx, 0, z_lr))   # left, Yp inward
T_roll_x = frame([(0, 0, 1), (0, 1, 0), (-1, 0, 0)], ROLLER_RAIL, (0, -ly, z_ur))  # front
# RollerMount in roller coordinates: up = roller +Xp, along the tube = roller +Yp (inward).
T_mount = frame([(0, 0, 1), (1, 0, 0), (0, 1, 0)], (67.5, 80.22, 35.3), (128.1, 118.12, 37.5))
MOTOR_C = (67.5, 124.69, 6 + NEMA[1] / 2)
ROLLER_HALF = 37.7      # roller Yp 147.7 - rail 110: how far the roller reaches inboard of its rail


def rollers(xg, yg):
    out = []
    for label, T, axis in [
        ("Roller Y left", compose(at(0, yg), T_roll_y), "X"),
        ("Roller Y right", compose(MIRROR_X, compose(at(0, yg), T_roll_y)), "X"),
        ("Roller X front", compose(at(xg, 0), T_roll_x), "Y"),
        ("Roller X back", compose(MIRROR_Y, compose(at(xg, 0), T_roll_x)), "Y"),
    ]:
        Tm = compose(T, T_mount)
        out.append(bd.Compound(label=label, children=[
            part("roller", T, label_m("Roller", T), A),
            part("roller_mount", Tm, "RollerMount", B),
            nema(apply(Tm, MOTOR_C), axis, "Stepper NEMA17"),
        ]))
    return out


# ---- middle and Z axis, placed from bolt B (the middle's vertical tension bolt) ----
RM = [(S2, -S2, 0), (S2, S2, 0), (0, 0, 1)]          # middle frame: front (-Ym) faces the 0,0 corner
RM_FLIP = [(-S2, S2, 0), (S2, S2, 0), (0, 0, -1)]     # the same, upside down about Ym
RM_180 = [(-S2, S2, 0), (-S2, -S2, 0), (0, 0, 1)]     # turned 180 about Z (Z plates)
zl = C["z_rail"]
gap = P["z_mount_gap"]
# XYZ heights: each plate's mid-plane level with the XY ears (tube -46.5 / +74 on both XYs).
XYZ_MID_LO = z_gx - 46.5
XYZ_MID_HI = z_gx + 74.0
z_xyz_top = XYZ_MID_HI + 10.5       # top face of the upper XYZ (21 thick)
NUT_H = 3.5
# Lowest the Z axis can go: Z Lower resting on the T8 nut flange.
zrb_min = z_xyz_top + NUT_H - (zl - 30 - gap)


# The red XYs: the X-gantry XY upside down (stem below its tube, reaching -X), the Y-gantry XY stem
# above its tube, reaching -Y. Both stems share two holes: the 10 mm one (Yp 71.83, Zp 78.16) and a
# bolt hole 16.5 behind it on the diagonal (Yp 83.5, Zp 89.83). The XYZs sit on them: leadscrew
# (T8 nut hole) through the first, the XYZ centre-back hole (127.01) over the second.
XY_X_GANTRY = [(0, 0, -1), (0, 1, 0), (1, 0, 0)]
XY_Y_GANTRY = [(0, 0, 1), (1, 0, 0), (0, 1, 0)]
XY_BOLT = (116.25, 71.83, 78.16)
B_TO_TUBE = 107.2 - 71.83


def middle(xg, yg, zrb):
    bx, by = xg - B_TO_TUBE, yg - B_TO_TUBE

    def mw(mx, my, z):
        """XYZ STL plan coordinates -> machine, with the T8 nut hole on the XY stems' 10 mm hole."""
        dx, dy = mx - LEAD_M[0], my - LEAD_M[1]
        return (bx + S2 * dx + S2 * dy, by - S2 * dx + S2 * dy, z)

    def mf(cols, local, mxy, z):
        return frame(cols, local, mw(*mxy, z))

    core = [
        ("xyz", mf(RM, (*XYZ_B, 0), XYZ_B, XYZ_MID_LO - 10.5), "XYZ", A),
        ("gantry_spacer", mf(RM, (102.5, 97.59, 0), XYZ_B, XYZ_MID_LO - 4.0), "Gantry Spacer", A),
        ("xy", frame(XY_X_GANTRY, XY_BOLT, (bx, by, z_gx)), "XY (X gantry)", B),
        ("xy", frame(XY_Y_GANTRY, XY_BOLT, (bx, by, z_gy)), "XY (Y gantry)", B),
        ("gantry_spacer", mf(RM_FLIP, (102.5, 97.59, 0), XYZ_B, XYZ_MID_HI + 4.0), "Gantry Spacer", A),
        ("xyz", mf(RM_FLIP, (*XYZ_B, 0), XYZ_B, z_xyz_top), "XYZ", A),
    ]
    rt = zrb + zl
    zaxis = [
        ("z_motor", mf(RM_180, (102.5, 153.65, 15), (102.5, 86.33), rt), "Z Motor", B),
        ("z_lower", mf(RM_180, (102.5, 114.79, 15), (102.5, 86.33), rt - 15 - gap), "Z Lower", B),
        ("tool_mount", mf(RM, (102.5, 91.49, 0), (102.5, 86.33), zrb), "Tool Mount (M4)", B),
    ]
    prims = []
    for mxy in Z_RAILS_M:
        zaxis.append(("nut_trap", mf([(0, 0, 1), (S2, -S2, 0), (S2, S2, 0)], (47, 102.2, 6.65), mxy, zrb),
                      "Nut Trap", A))
        prims.append(tube(zl, "Z rail", mw(*mxy, zrb + zl / 2)))
    lx_, ly_, _ = mw(*LEAD_M, 0)
    lead_top = rt - 15 - gap
    zm = bd.Box(NEMA[0], NEMA[0], NEMA[1]).moved(bd.Location((lx_, ly_, rt + NEMA[1] / 2), (0, 0, 45)))
    zm.label, zm.color = "Stepper NEMA17 (Z)", MOTOR
    prims += [
        zm,
        rod(19, gap, (lx_, ly_, lead_top), "Coupler 5-8 mm", STEEL),
        rod(8, C["leadscrew"], (lx_, ly_, lead_top - C["leadscrew"]), "Leadscrew T8", STEEL),
        rod(22, NUT_H, (lx_, ly_, z_xyz_top), "T8 nut", BRASS),
    ]
    return core, zaxis, prims, mw(*TOOL_FACE_M, zrb)


# ---- travel ------------------------------------------------------------------------
# Rollers stop against the corners: corner 23.5 inboard of the leg line, roller 37.5 each side
# of its gantry tube.
xg_lo, xg_hi = -lx + 61.0, lx - 61.0
yg_lo, yg_hi = -ly + 61.0, ly - 61.0
# The middle and Z axis stop against the rollers on the other axis (plan bounding boxes, so
# slightly conservative).
probe_core, probe_z, _, tool0 = middle(0.0, 0.0, 0.0)
rel_lo, rel_hi = [1e9] * 2, [-1e9] * 2
for name, T, *_ in probe_core + probe_z:
    lo, hi = mesh_bounds(name, T)
    rel_lo = [min(rel_lo[k], lo[k]) for k in range(2)]
    rel_hi = [max(rel_hi[k], hi[k]) for k in range(2)]
xg_lo = max(xg_lo, -(lx - ROLLER_HALF) - rel_lo[0])
xg_hi = min(xg_hi, (lx - ROLLER_HALF) - rel_hi[0])
yg_lo = max(yg_lo, -(ly - ROLLER_HALF) - rel_lo[1])
yg_hi = min(yg_hi, (ly - ROLLER_HALF) - rel_hi[1])
tool_dx, tool_dy = tool0[0], tool0[1]            # tool-mount face centre relative to (xg, yg)
wcx = (xg_lo + xg_hi) / 2 + tool_dx
wcy = (yg_lo + yg_hi) / 2 + tool_dy

xg = xg_lo + P["pose"]["x"] * (xg_hi - xg_lo)
yg = yg_lo + P["pose"]["y"] * (yg_hi - yg_lo)
# Lowest Z: rail bottoms on the table, or Z Lower on the T8 nut if that comes first.
zrb_low = max(0.0, zrb_min)
zrb = zrb_low + P["pose"]["z"] * C["z_work"]
core, zaxis, zprims, tool = middle(xg, yg, zrb)

gantry = [tube(C["x_rail"], "X gantry tube", (0, yg, z_gx), "X"),
          tube(C["y_rail"], "Y gantry tube", (xg, 0, z_gy), "Y")]
table = box((max(C["x_rail"], 1000), max(C["y_rail"], 1000), 18), (0, 0, -9), "Table top", TABLE)
work = box((C["x_work"], C["y_work"], 0.5), (wcx, wcy, 0.25), "Usable area (V1 cut list)", WORK)

if P.get("debug_report"):
    raise RuntimeError(repr({
        "gantry_travel": (round(xg_hi - xg_lo, 1), round(yg_hi - yg_lo, 1)),
        "rel_middle_xy": ([round(v, 1) for v in rel_lo], [round(v, 1) for v in rel_hi]),
        "tool_from_gantry": (round(tool_dx, 1), round(tool_dy, 1)),
        "work_centre": (round(wcx, 1), round(wcy, 1)),
        "z": {"leg_lift": round(leg_lift, 2), "lock_top": round(z_lt, 2), "lower_rail": round(z_lr, 2), "upper_rail": round(z_ur, 2),
              "x_gantry": round(z_gx, 2), "y_gantry": round(z_gy, 2), "xyz_top": round(z_xyz_top, 2),
              "z_rail_bottom_min": round(zrb_min, 2), "z_rail_bottom_low": round(zrb_low, 2)},
    }))

model = bd.Compound(label="MPCNC Burly J", children=[
    table, work,
    bd.Compound(label="Base", children=[bd.Compound(label="Corners", children=corners),
                                        bd.Compound(label="Rails", children=rails)]),
    bd.Compound(label="Gantry", children=[*rollers(xg, yg), *gantry]),
    bd.Compound(label="Middle", children=[part(n, T, l, c) for n, T, l, c in core]),
    bd.Compound(label="Z axis", children=[*(part(n, T, l, c) for n, T, l, c in zaxis), *zprims]),
])
