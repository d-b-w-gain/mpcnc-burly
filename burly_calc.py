"""V1's Burly cut list (docs.v1e.com/mpcnc/burly/conduit): every X and Y tube - both rails and the
gantry - is the same length, and the usable area is that length less 264 mm. Legs are
usable height - 13 unless params.json gives the measured length.
Run directly to print the cut list for params.json."""
import json
from pathlib import Path

HERE = Path(__file__).parent


def load_params():
    return json.loads((HERE / "params.json").read_text())


def cut_list(P):
    c = {
        "x_rail": P["rail_x"], "y_rail": P["rail_y"],
        "x_work": P["rail_x"] - 264, "y_work": P["rail_y"] - 264, "z_work": P["z_work"],
        "z_rail": P["z_work"] + 190,
        "leg": P.get("leg", P["z_work"] - 13),
        "leadscrew": P["z_work"] + 76,
    }
    c["tube_total"] = 3 * c["x_rail"] + 3 * c["y_rail"] + 2 * c["z_rail"] + 4 * c["leg"]
    return c


if __name__ == "__main__":
    c = cut_list(load_params())
    print(f"MPCNC Burly J, rails {c['x_rail']} x {c['y_rail']} mm")
    print(f"usable area   {c['x_work']} x {c['y_work']} x {c['z_work']} mm")
    for k, q in [("x_rail", 3), ("y_rail", 3), ("z_rail", 2), ("leg", 4)]:
        print(f"  {q} x {k:8s} {c[k]:7.1f} mm")
    print(f"leadscrew     {c['leadscrew']} mm (T8)")
    print(f"tube total    {c['tube_total']} mm")
