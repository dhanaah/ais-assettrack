"""AIS AssetTrack - end-to-end process flow, A3 landscape (one sheet). Writes AssetTrack_Process_Flow_A3.html and,
with --pdf, renders the PDF with Playwright. Developed by DT"""
import html, sys, os

W, H = 1587, 1123          # A3 landscape at 96 dpi
OUT = os.path.dirname(os.path.abspath(__file__))
VER = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "server 1.19 · HHT 2.8"

parts, edges = [], []
BOX = {}
e = html.escape


def box(id_, x, y, w, h, kind, title, subs=()):
    BOX[id_] = (x, y, w, h, "box")
    s = [f'<g class="n {kind}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7"/>']
    lines = [title] + list(subs)
    lh = 14.5; top = y + h / 2 - (len(lines) - 1) * lh / 2 + 4
    for i, t in enumerate(lines):
        s.append(f'<text x="{x + w / 2}" y="{top + i * lh}" text-anchor="middle" class="{"t" if i == 0 else "s"}">{e(t)}</text>')
    s.append("</g>"); parts.append("".join(s))


def dia(id_, cx, cy, w, h, title, subs=()):
    BOX[id_] = (cx - w / 2, cy - h / 2, w, h, "dia")
    pts = f"{cx},{cy - h / 2} {cx + w / 2},{cy} {cx},{cy + h / 2} {cx - w / 2},{cy}"
    s = [f'<g class="n ctrl"><polygon points="{pts}"/>']
    lines = [title] + list(subs); lh = 13.5; top = cy - (len(lines) - 1) * lh / 2 + 4
    for i, t in enumerate(lines):
        s.append(f'<text x="{cx}" y="{top + i * lh}" text-anchor="middle" class="{"t" if i == 0 else "s"}">{e(t)}</text>')
    s.append("</g>"); parts.append("".join(s))


def P(id_, side, off=0.5):
    x, y, w, h, _ = BOX[id_]
    return {"l": (x, y + h * off), "r": (x + w, y + h * off), "t": (x + w * off, y), "b": (x + w * off, y + h)}[side]


def edge(pts, kind="", label=None, lp=None, la="middle"):
    d = "M" + " L".join(f"{a},{b}" for a, b in pts)
    edges.append(f'<path class="edge {kind}" d="{d}" marker-end="url(#ar{"-" + kind if kind else ""})"/>')
    if label:
        x, y = lp or ((pts[0][0] + pts[-1][0]) / 2, (pts[0][1] + pts[-1][1]) / 2 - 6)
        edges.append(f'<text class="elabel {kind}" x="{x}" y="{y}" text-anchor="{la}">{e(label)}</text>')


def lane(y, h, label, color="lane"):
    n = len(label)
    if (n - 1) * 23 + 30 > h:   # too long to stack: write it turned sideways
        parts.insert(0, f'<rect class="{color}" x="40" y="{y}" width="{W - 80}" height="{h}" rx="10"/>'
                        f'<text class="laneLabel" style="font-size:16px;letter-spacing:2px" text-anchor="middle" transform="translate(66,{y + h / 2}) rotate(-90)">{e(label)}</text>')
        return
    sp = 23; letters = "".join(f'<tspan x="60" dy="{0 if i == 0 else sp}">{c}</tspan>' for i, c in enumerate(label))
    ty = y + h / 2 - (n - 1) * sp / 2 + 6
    parts.insert(0, f'<rect class="{color}" x="40" y="{y}" width="{W - 80}" height="{h}" rx="10"/>'
                    f'<text class="laneLabel" text-anchor="middle" y="{ty}">{letters}</text>')


# ------------------------------------------------------------------ lanes
L1, L2, L3, L4 = (186, 232), (430, 176), (618, 300), (930, 128)
lane(*L1, "DISPATCH"); lane(*L2, "CUSTOMER", "lane cust"); lane(*L3, "RETURN"); lane(*L4, "INTERPLANT")

# ------------------------------------------------------------------ masters strip
mx = [("PLANTS & USERS", ["One server · plant chosen at sign-in", "Roles · extra plants · Customer Staff"]),
      ("PALLETS & TYPES", ["QR AIS-plant-type-serial-global", "Type: value · HSN · L×W×H · weight"]),
      ("CUSTOMERS & TRANSPORTERS", ["Auto-created from the GCS file", "Holding days · e-mails · vehicles"]),
      ("CUSTOMER HHT", ["Paired by QR from the web", "Staff sign-in · works offline"]),
      ("HHT SETUP", ["Scan server QR · Online / Offline", "Any BT printer · scanner or camera"]),
      ("INTEGRATIONS", ["Bench trips (plant-wise) · GCS FTP", "per plant · EBS challan / GCS-IN"])]
bw = (W - 140 - 5 * 12) / 6
for i, (h, ls) in enumerate(mx):
    x = 100 + i * (bw + 12)
    parts.append(f'<g class="master"><rect x="{x}" y="104" width="{bw}" height="66" rx="6"/><text class="h" x="{x + 10}" y="123">{e(h)}</text>'
                 + "".join(f'<text x="{x + 10}" y="{141 + j * 15}">{e(t)}</text>' for j, t in enumerate(ls)) + "</g>")

# ------------------------------------------------------------------ DISPATCH
y1 = 228; bh = 62
box("bench", 100, y1, 158, bh, "ext", "Dispatch Bench", ["plant-wise trip · picks LPN", "PDI done here"])
box("erp", 282, y1, 158, bh, "ext", "ERP invoice + GCS", ["GCS file to the plant's", "FTP folder"])
box("inbox", 464, y1, 168, bh, "app", "GCS inbox → load sheet", ["per plant · joined with", "its Bench trip (one record)"])
box("load", 656, y1, 160, bh, "step", "HHT · Vehicle loading", ["scan part card + pallet", "(scanner or camera)"])
dia("pdi", 912, y1 + bh / 2, 150, 96, "Card in GCS?", ["PDI passed for", "this vehicle"])
dia("fin", 1098, y1 + bh / 2, 160, 96, "Finish loading", ["qty vs invoice", "missing / extra"])
box("gp", 1206, y1, 158, bh, "app", "Gate pass + Challan", ["auto PDF · signed GCS QR", "GCS slip on BT printer"])
box("out", 1392, y1, 150, bh, "step", "AIS OUT gate", ["scan GCS QR", "vehicle released"])
box("stop", 838, 346, 148, 52, "warn", "STOP – do PDI", ["wrong vehicle refused"])
box("ebs", 1206, 346, 158, 52, "ext", "Oracle EBS", ["challan · e-way bill"])
box("atc", 1392, 346, 150, 52, "ok", "AT CUSTOMER", ["holding days start"])
edge([P("bench", "r"), P("erp", "l")]); edge([P("erp", "r"), P("inbox", "l")]); edge([P("inbox", "r"), P("load", "l")])
edge([P("load", "r"), (837, y1 + bh / 2)])
edge([(987, y1 + bh / 2), (1018, y1 + bh / 2)], "yes", "yes", (1002, y1 + bh / 2 - 8))
edge([(912, y1 + bh / 2 + 48), P("stop", "t")], "no", "no", (922, 326), "start")
edge([(1178, y1 + bh / 2), P("gp", "l")], "yes", "ok", (1192, y1 + bh / 2 - 8))
edge([(1098, y1 + bh / 2 - 48), (1098, 206), (736, 206), P("load", "t")], "no", "short → keep loading", (918, 200))
edge([P("gp", "r"), P("out", "l")]); edge([P("ebs", "t"), P("gp", "b")], "ext")
edge([P("out", "b"), P("atc", "t")])
parts.append(f'<text class="note" x="466" y="{y1 + bh + 24}">HHT gets the sheet within 30 s · only the chosen plant\'s lists</text>')

# ------------------------------------------------------------------ CUSTOMER
y2 = 470; ch = 70
box("recv", 1392, y2, 150, ch, "cust", "Receive delivery", ["staff scan each pallet", "while unloading"])
box("recvres", 1196, y2, 168, ch, "app", "Received/missing/extra", ["visible to AIS"])
box("hold", 990, y2, 178, ch, "app", "Holding days · reminders", ["mail before / after limit", "escalation"])
box("retA", 702, y2, 190, ch, "cust", "Return empty pallets · A", ["scan pallets · pick vehicle", "customer DC if any"])
box("slip", 490, y2, 184, ch, "cust", "Return slip printed", ["no. auto · signed QR", "offline: RO- slip from HHT"])
box("veh", 290, y2, 172, ch, "step", "Vehicle to AIS", ["with slip, document", "or nothing"])
edge([P("atc", "b"), P("recv", "t")]); edge([P("recv", "l"), P("recvres", "r")])
edge([P("retA", "l"), P("slip", "r")]); edge([P("slip", "l"), P("veh", "r")])
edge([P("recvres", "l"), P("hold", "r")]); edge([P("hold", "l"), P("retA", "r")], "", "emptied", (921, P("hold", "l")[1] - 9))
parts.append(f'<text class="note" x="702" y="{y2 + ch + 22}">Customer HHT: staff sign in with their own user · works without network, sends later</text>')

# ------------------------------------------------------------------ RETURN
dia("with", 170, 668, 150, 84, "Vehicle brings?", [])
box("inA", 330, 640, 176, 58, "step", "Scan return slip QR", ["Option A (or offline RO- slip)"])
box("inB", 330, 724, 176, 70, "step", "Make slip B at gate", ["count + photo of customer", "document → read & matched"])
box("inP", 330, 818, 176, 58, "step", "Scan plant challan", ["other AIS plant: challan only"])
box("gcsin", 540, 718, 168, 82, "app", "Gate inward register", ["IN gate · one entry no.", "for every inward vehicle", "+ GCS inward (ERP)"])
box("yard", 740, 724, 190, 70, "step", "Pallet yard receiving", ["scan each pallet · slip /", "document list + photo shown"])
dia("rec", 1012, 759, 150, 92, "Reconcile", ["received vs", "slip / document"])
box("avail", 1130, 642, 172, 54, "ok", "AVAILABLE", ["back in plant stock"])
box("held", 1130, 732, 172, 54, "warn", "HELD – other plant", ["owner plant alerted"])
box("disc", 1130, 822, 172, 60, "warn", "Discrepancy queue", ["short · extra · unknown", "damaged · supervisor PIN"])
box("rep", 1360, 660, 182, 210, "app", "Reports & dashboard", ["plant position", "at customer · aging", "missed scans", "customer receipts", "Excel / PDF everywhere"])
edge([P("veh", "b"), (376, 600), (170, 600), (170, 626)])
edge([(245, 668), P("inA", "l")], "", "slip", (262, 660), "start")
edge([(170, 710), (170, 759), P("inB", "l")], "", "no slip", (180, 752), "start")
edge([(170, 759), (170, 847), P("inP", "l")], "", "plant challan", (180, 840), "start")
edge([P("inA", "r"), (522, 669), (522, 740), (540, 740)]); edge([P("inB", "r"), P("gcsin", "l")])
edge([P("inP", "r"), (522, 847), (522, 778), (540, 778)])
edge([P("gcsin", "r"), P("yard", "l")])
edge([P("yard", "r"), (937, 759)])
edge([(1012, 713), (1012, 669), P("avail", "l")], "yes", "match", (1030, 662), "start")
edge([(1087, 759), P("held", "l")], "", "other plant", (1092, 728), "start")
edge([(1012, 805), (1012, 852), P("disc", "l")], "no", "mismatch", (1022, 845), "start")
edge([P("avail", "r"), (1360, 669)]); edge([P("disc", "r"), (1360, 852)])

# ------------------------------------------------------------------ PLANT <-> PLANT
y4 = 966; ph = 58
box("emp", 100, y4, 176, ph, "step", "Other-plant pallets", ["emptied in FGWH / Packing"])
box("yl", 300, y4, 176, ph, "step", "HHT · Yard loading", ["owner plant · scan pallets"])
box("ch", 500, y4, 176, ph, "ext", "Challan + e-way bill", ["EBS / app challan"])
box("o2", 700, y4, 150, ph, "step", "OUT gate", ["scan challan QR"])
box("i2", 874, y4, 190, ph, "step", "Owner plant IN gate", ["scans the same challan"])
box("y2", 1088, y4, 176, ph, "step", "Owner plant Yard", ["scan each pallet"])
box("ok2", 1288, y4, 160, ph, "ok", "AVAILABLE at home", [])
for a, b in (("emp", "yl"), ("yl", "ch"), ("ch", "o2"), ("o2", "i2"), ("i2", "y2"), ("y2", "ok2")):
    edge([P(a, "r"), P(b, "l")], "ext" if "ch" in (a,) else "")

# ------------------------------------------------------------------ page
svg = f'''<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="AIS AssetTrack end-to-end process flow">
<defs>{"".join(f'<marker id="ar{s}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="mk{s}"/></marker>' for s in ("", "-ext", "-yes", "-no"))}</defs>
<text class="title" x="40" y="56">AIS AssetTrack — End-to-End Process Flow</text>
<text class="sub" x="40" y="80">Returnable pallets · AIS plant → OEM / OES / AFM customer → AIS · one server for all plants · revised Oct 2026 · {e(VER)}</text>
{"".join(f'<g class="lg"><rect x="{x}" y="{y}" width="13" height="13" rx="3" class="{c}"/><text x="{x + 19}" y="{y + 11}">{e(t)}</text></g>' for x, y, c, t in
   [(1010, 30, "lgs", "Scan step (HHT / gate)"), (1180, 30, "lga", "AssetTrack function"), (1340, 30, "lgc", "Control check"),
    (1010, 52, "lgx", "External (Bench/ERP/EBS)"), (1180, 52, "lgu", "Customer HHT step"), (1340, 52, "lgo", "Normal end state"), (1480, 52, "lgw", "Exception")])}
{"".join(parts)}
{"".join(edges)}
<text class="foot" x="40" y="{H - 34}">Rules: every inward (slip A, slip B, plant challan) is registered at the IN gate · a part card not in the GCS is stopped (do PDI) · Option B slips are a count, knocked off at the pallet yard</text>
<text class="foot" x="40" y="{H - 16}">AIS AssetTrack · process flow A3 · Developed by DT</text>
</svg>'''

css = """
@page{size:420mm 297mm;margin:0}
:root{--bg:#f3f4f2;--paper:#fff;--fg:#1b1f1d;--mute:#5c655f;--line:#c9cfca;--lane:#ebeeec;--cust:#e6f4f1;--acc:#0b5f8a;--acc2:#d5e8f2;
--ctrl:#b45309;--ctrl2:#fbe7cf;--ok:#1f7a3a;--ok2:#d9efdf;--warn:#9b1c1c;--warn2:#f6dada;--ext:#5b3f9e;--ext2:#e6def5;--cu:#0f766e;--cu2:#ccefe9}
html,body{margin:0;background:var(--bg)}body{padding:0}
svg{display:block;width:100%;height:auto;background:var(--paper);font-family:Inter,system-ui,sans-serif}
.title{font-family:"Inter Display",Inter,sans-serif;font-weight:800;font-size:30px;fill:var(--fg)}
.sub{font-size:14px;fill:var(--mute)}
.lane{fill:var(--lane)}.lane.cust{fill:var(--cust)}
.laneLabel{font-family:"Inter Display",Inter,sans-serif;font-weight:800;font-size:19px;fill:#7b847e}
.n text{fill:var(--fg)}.n .t{font-weight:700;font-size:13px}.n .s{font-size:11px;fill:var(--mute)}
.step rect{fill:var(--paper);stroke:var(--fg);stroke-width:1.4}
.app rect{fill:var(--acc2);stroke:var(--acc);stroke-width:1.4}
.ctrl polygon{fill:var(--ctrl2);stroke:var(--ctrl);stroke-width:1.6}
.ext rect{fill:var(--ext2);stroke:var(--ext);stroke-width:1.4;stroke-dasharray:5 3}
.cust rect{fill:var(--cu2);stroke:var(--cu);stroke-width:1.6}
.ok rect{fill:var(--ok2);stroke:var(--ok);stroke-width:1.5}
.warn rect{fill:var(--warn2);stroke:var(--warn);stroke-width:1.5}
.edge{fill:none;stroke:var(--fg);stroke-width:1.5}.edge.ext{stroke:var(--ext);stroke-dasharray:5 3}.edge.yes{stroke:var(--ok)}.edge.no{stroke:var(--warn)}
.mk{fill:var(--fg)}.mk-ext{fill:var(--ext)}.mk-yes{fill:var(--ok)}.mk-no{fill:var(--warn)}
.elabel{font-size:11px;fill:var(--mute);font-weight:600}.elabel.yes{fill:var(--ok)}.elabel.no{fill:var(--warn)}
.master rect{fill:var(--paper);stroke:var(--line);stroke-width:1.2}.master text{font-size:11.5px;fill:var(--fg)}
.master .h{font-weight:700;font-size:11.5px;fill:var(--mute);letter-spacing:1.2px}
.note{font-size:11.5px;fill:var(--mute);font-style:italic}.foot{font-size:11.5px;fill:var(--mute)}
.lg text{font-size:12px;fill:var(--mute)}
.lgs{fill:var(--paper);stroke:var(--fg)}.lga{fill:var(--acc2);stroke:var(--acc)}.lgc{fill:var(--ctrl2);stroke:var(--ctrl)}
.lgx{fill:var(--ext2);stroke:var(--ext);stroke-dasharray:3 2}.lgu{fill:var(--cu2);stroke:var(--cu)}.lgo{fill:var(--ok2);stroke:var(--ok)}.lgw{fill:var(--warn2);stroke:var(--warn)}
"""
page = f'<!doctype html><html><head><meta charset="utf-8"><title>AssetTrack Process Flow A3</title><style>{css}</style></head><body>{svg}</body></html>'
hp = os.path.join(OUT, "AssetTrack_Process_Flow_A3.html")
open(hp, "w", encoding="utf-8").write(page)
print("html", hp)
if "--pdf" in sys.argv:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell")
        pg = b.new_page(viewport={"width": W, "height": H}); pg.goto("file://" + hp); pg.wait_for_timeout(300)
        pg.pdf(path=os.path.join(OUT, "AssetTrack_Process_Flow_A3.pdf"), width="420mm", height="297mm", print_background=True, margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        pg.screenshot(path=os.path.join(OUT, "preview.png"))
        b.close()
    print("pdf done")
