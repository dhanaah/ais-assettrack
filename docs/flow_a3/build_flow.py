"""AIS AssetTrack - end-to-end process flow, A3 landscape (one sheet). Writes AssetTrack_Process_Flow_A3.html and,
with --pdf, renders the PDF with Playwright. Developed by DT"""
import html, sys, os

W, H = 1587, 1123          # A3 landscape at 96 dpi
OUT = os.path.dirname(os.path.abspath(__file__))
VER = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "server 1.37.2 · HHT 2.23.0"

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
                        f'<text class="laneLabel" style="font-size:{13 if h < 120 else 16}px;letter-spacing:{1 if h < 120 else 2}px" text-anchor="middle" transform="translate(66,{y + h / 2}) rotate(-90)">{e(label)}</text>')
        return
    sp = 23; letters = "".join(f'<tspan x="60" dy="{0 if i == 0 else sp}">{c}</tspan>' for i, c in enumerate(label))
    ty = y + h / 2 - (n - 1) * sp / 2 + 6
    parts.insert(0, f'<rect class="{color}" x="40" y="{y}" width="{W - 80}" height="{h}" rx="10"/>'
                    f'<text class="laneLabel" text-anchor="middle" y="{ty}">{letters}</text>')


# ------------------------------------------------------------------ lanes
L1, L2, L3, L4 = (186, 320), (518, 150), (680, 270), (962, 100)
lane(*L1, "DISPATCH"); lane(*L2, "CUSTOMER", "lane cust"); lane(*L3, "RETURN"); lane(*L4, "INTERPLANT")

# ------------------------------------------------------------------ masters strip
mx = [("PLANTS & CUSTOMERS", ["From the Dispatch Bench (Oracle no.)", "read-only · holding days kept here"]),
      ("USERS & ROLES", ["One server · plant chosen at sign-in", "one permission per HHT button"]),
      ("PALLETS & TYPES", ["QR AIS-plant-type-serial-global", "Type: value · HSN · L×W×H · weight"]),
      ("CUSTOMER HHT", ["Paired by QR · own staff sign-in", "FortiClient VPN · works offline"]),
      ("HHT SETUP", ["Scanner only (no typing) or camera", "BT printer: return slips only"]),
      ("INTEGRATIONS", ["Bench: SQL tables or API (auto)", "GCS FTP per plant · Oracle challan"])]
bw = (W - 140 - 5 * 12) / 6
for i, (h, ls) in enumerate(mx):
    x = 100 + i * (bw + 12)
    parts.append(f'<g class="master"><rect x="{x}" y="104" width="{bw}" height="66" rx="6"/><text class="h" x="{x + 10}" y="123">{e(h)}</text>'
                 + "".join(f'<text x="{x + 10}" y="{141 + j * 15}">{e(t)}</text>' for j, t in enumerate(ls)) + "</g>")

# ------------------------------------------------------------------ DISPATCH - row A: from production to a clean load sheet
ya = 206; bh = 64; ma = ya + bh / 2
box("prod", 100, ya, 142, bh, "step", "Production → FGWH", ["pallet card scan", "FGWH = centre for all FG"])
box("bench", 262, ya, 152, bh, "ext", "Dispatch Bench", ["plant-wise trip", "picks LPN pallet.card"])
box("bpdi", 434, ya, 152, bh, "ext", "Bench PDI", ["Accepted · Hold · Pending", "Rejected (final)"])
box("erp", 606, ya, 164, bh, "ext", "ERP invoice + GCS", ["GCS file to the plant's", "FTP folder"])
box("inbox", 790, ya, 166, bh, "app", "GCS inbox", ["auto pull per plant", "cancel · re-send · reopen"])
dia("match", 1066, ma, 178, 92, "PDI match?", ["every card on one Bench", "trip · PDI Accepted"])
box("ready", 1392, ya, 150, bh, "app", "Load sheet ready", ["GCS + Bench trip = one", "record · PDI sheet PDF"])
box("hard", 966, 294, 200, 46, "warn", "HARD STOP – fix first", ["no trip · not PDI OK · not invoiced"])
box("lreq", 1190, 294, 190, 46, "app", "No cards → vehicle link", ["supervisor asks · admin approves"])
edge([P("prod", "r"), P("bench", "l")]); edge([P("bench", "r"), P("bpdi", "l")]); edge([P("bpdi", "r"), P("erp", "l")])
edge([P("erp", "r"), P("inbox", "l")]); edge([P("inbox", "r"), (977, ma)])
edge([(1155, ma), P("ready", "l")], "yes", "yes", (1272, ma - 8))
edge([(1066, ma + 46), P("hard", "t")], "no", "no", (1074, 292), "start")
edge([P("hard", "r"), P("lreq", "l")])
edge([P("lreq", "r"), (1429, 317), (1429, ya + bh)])
parts.append(f'<text class="note" x="264" y="{ya + bh + 22}">AssetTrack reads the Bench every 30 s · re-picked / rejected cards update the sheet</text>')
parts.append(f'<text class="note" x="264" y="{ya + bh + 38}">A cancelled GCS stops · re-sent by the ERP it opens again</text>')

# ------------------------------------------------------------------ DISPATCH - row B (right to left): loading to the customer
yb = 386; mb = yb + bh / 2
box("load", 1392, yb, 150, bh, "step", "HHT · Vehicle loading", ["scan GCS, then each", "pallet QR · new labels ok"])
dia("card", 1252, mb, 150, 84, "Cards OK?", ["in GCS · PDI Accepted", "not removed"])
dia("fin", 1050, mb, 166, 84, "Last pallet?", ["loaded = GCS pallets", "→ finishes by itself"])
box("gp", 740, yb, 196, bh, "app", "Challan + gate pass", ["Oracle challan · gate QR only", "after finish · plant printer"])
box("out", 528, yb, 182, bh, "step", "AIS OUT gate", ["scan challan / gate QR", "vehicle released"])
box("atc", 310, yb, 182, bh, "ok", "AT CUSTOMER", ["holding days start"])
box("cstop", 1178, 470, 148, 30, "warn", "STOP – keep it off", [])
box("ebs", 760, 470, 156, 30, "ext", "Oracle EBS · e-way bill", [])
edge([(1467, ya + bh), P("load", "t")])
edge([P("load", "l"), (1327, mb)])
edge([(1177, mb), (1133, mb)], "yes", "yes", (1155, mb - 8))
edge([(1252, mb + 42), P("cstop", "t")], "no", "no", (1244, 468), "end")
edge([(1050, mb - 42), (1050, 362), (1437, 362), (1437, yb)], "no", "short → keep loading", (1180, 356))
edge([(967, mb), P("gp", "r")], "yes", "done", (952, mb - 8))
edge([P("gp", "l"), P("out", "r")]); edge([P("out", "l"), P("atc", "r")])
edge([P("ebs", "t"), P("gp", "b")], "ext")
parts.append('<g class="master"><rect x="100" y="386" width="200" height="104" rx="6"/>'
             '<text class="h" x="110" y="404">PDI STATES</text>'
             + "".join(f'<text x="110" y="{422 + j * 15}">{e(t)}</text>' for j, t in enumerate(
                 ["Accepted = loadable", "Hold · Pending · not picked = wait", "Rejected = removed for good",
                  "PDI done, not invoiced = hold out"])) + "</g>")

# ------------------------------------------------------------------ CUSTOMER (left to right)
y2 = 548; ch = 66
box("recv", 100, y2, 172, ch, "cust", "Receive delivery", ["staff scan each pallet", "while unloading"])
box("recvres", 296, y2, 178, ch, "app", "Received / missing / extra", ["visible to AIS"])
box("hold", 498, y2, 190, ch, "app", "Holding days · reminders", ["mail before / after limit", "escalation"])
box("retA", 718, y2, 200, ch, "cust", "Return empty pallets · A", ["when emptied · scan pallets", "pick vehicle · customer DC"])
box("slip", 948, y2, 192, ch, "cust", "Return slip printed", ["BT printer · no. auto", "signed QR (offline: RO-)"])
box("veh", 1170, y2, 172, ch, "step", "Vehicle to AIS", ["with slip, document", "or nothing"])
edge([P("atc", "b"), (401, 510), (186, 510), P("recv", "t")])
edge([P("recv", "r"), P("recvres", "l")]); edge([P("recvres", "r"), P("hold", "l")])
edge([P("hold", "r"), P("retA", "l")])
edge([P("retA", "r"), P("slip", "l")]); edge([P("slip", "r"), P("veh", "l")])
for j, t in enumerate(["Customer HHT works", "without network, sends", "when back on VPN"]):
    parts.append(f'<text class="note" x="1362" y="{y2 + 16 + j * 16}">{t}</text>')

# ------------------------------------------------------------------ RETURN
o = 62
dia("with", 170, 668 + o, 150, 84, "Vehicle brings?", [])
box("inA", 330, 640 + o, 176, 58, "step", "Scan return slip QR", ["Option A (or offline RO- slip)"])
box("inB", 330, 724 + o, 176, 70, "step", "Make slip B at gate", ["count + document photo", "(required) · read & matched", "slip on BT printer"])
box("inP", 330, 818 + o, 176, 58, "step", "Scan plant challan", ["other AIS plant: challan only"])
box("gcsin", 540, 718 + o, 168, 82, "app", "Gate inward register", ["IN gate · one entry no.", "for every inward vehicle", "+ GCS inward (ERP)"])
box("yard", 740, 724 + o, 190, 70, "step", "Pallet yard receiving", ["only gate-endorsed inwards", "pallet QR only (no card)", "A: vs slip · B: photo → count"])
dia("rec", 1012, 759 + o, 150, 92, "Reconcile", ["received vs", "slip / document"])
box("avail", 1130, 642 + o, 172, 54, "ok", "AVAILABLE", ["back in plant stock"])
box("held", 1130, 732 + o, 172, 54, "warn", "HELD – other plant", ["owner plant alerted"])
box("disc", 1130, 822 + o, 172, 56, "warn", "Discrepancy queue", ["short · extra · unknown", "damaged · supervisor PIN"])
box("rep", 1360, 660 + o, 182, 206, "app", "Reports & dashboard", ["plant position", "at customer · aging", "missed scans", "customer receipts", "Excel / PDF everywhere"])
edge([P("veh", "b"), (1256, 674), (170, 674), (170, 626 + o)])
edge([(245, 668 + o), P("inA", "l")], "", "slip", (262, 660 + o), "start")
edge([(170, 710 + o), (170, 759 + o), P("inB", "l")], "", "no slip", (180, 752 + o), "start")
edge([(170, 759 + o), (170, 847 + o), P("inP", "l")], "", "plant challan", (180, 840 + o), "start")
edge([P("inA", "r"), (522, 669 + o), (522, 740 + o), (540, 740 + o)]); edge([P("inB", "r"), P("gcsin", "l")])
edge([P("inP", "r"), (522, 847 + o), (522, 778 + o), (540, 778 + o)])
edge([P("gcsin", "r"), P("yard", "l")])
edge([P("yard", "r"), (937, 759 + o)])
edge([(1012, 713 + o), (1012, 669 + o), P("avail", "l")], "yes", "match", (1030, 662 + o), "start")
edge([(1087, 759 + o), P("held", "l")], "", "other plant", (1092, 728 + o), "start")
edge([(1012, 805 + o), (1012, 850 + o), P("disc", "l")], "no", "mismatch", (1022, 843 + o), "start")
edge([P("avail", "r"), (1360, 669 + o)]); edge([P("disc", "r"), (1360, 850 + o)])

# ------------------------------------------------------------------ PLANT <-> PLANT
y4 = 983; ph = 58
box("emp", 100, y4, 176, ph, "step", "Other-plant pallets", ["emptied in FGWH / Packing"])
box("yl", 300, y4, 176, ph, "step", "HHT · Yard-Out", ["to the owner plant · scan"])
box("ch", 500, y4, 176, ph, "ext", "Challan + e-way bill", ["EBS / app challan"])
box("o2", 700, y4, 150, ph, "step", "OUT gate", ["scan challan QR"])
box("i2", 874, y4, 190, ph, "step", "Owner plant IN gate", ["scans the same challan"])
box("y2", 1088, y4, 176, ph, "step", "Owner plant Yard", ["scan each pallet"])
box("ok2", 1288, y4, 160, ph, "ok", "AVAILABLE at home", [])
for a_, b_ in (("emp", "yl"), ("yl", "ch"), ("ch", "o2"), ("o2", "i2"), ("i2", "y2"), ("y2", "ok2")):
    edge([P(a_, "r"), P(b_, "l")], "ext" if a_ == "ch" else "")

# ------------------------------------------------------------------ page
svg = f'''<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="AIS AssetTrack end-to-end process flow">
<defs>{"".join(f'<marker id="ar{s}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="mk{s}"/></marker>' for s in ("", "-ext", "-yes", "-no"))}</defs>
<text class="title" x="40" y="56">AIS AssetTrack — End-to-End Process Flow</text>
<text class="sub" x="40" y="80">Returnable pallets · AIS plant → OEM / OES / AFM customer → AIS · one server for all plants · revised 21 Oct 2026 · {e(VER)}</text>
{"".join(f'<g class="lg"><rect x="{x}" y="{y}" width="13" height="13" rx="3" class="{c}"/><text x="{x + 19}" y="{y + 11}">{e(t)}</text></g>' for x, y, c, t in
   [(1010, 30, "lgs", "Scan step (HHT / gate)"), (1180, 30, "lga", "AssetTrack function"), (1340, 30, "lgc", "Control check"),
    (1010, 52, "lgx", "External (Bench/ERP/EBS)"), (1180, 52, "lgu", "Customer HHT step"), (1340, 52, "lgo", "Normal end state"), (1480, 52, "lgw", "Exception")])}
{"".join(parts)}
{"".join(edges)}
<text class="foot" x="40" y="{H - 50}">Rules: a GCS loads only when every part card is on one Bench trip with PDI Accepted · the gate QR is printed only after loading is finished · a cancelled GCS cannot be loaded</text>
<text class="foot" x="40" y="{H - 34}">FGWH is the centre (no Production → Dispatch, no Dispatch ↔ Packing) · every inward is registered at the IN gate · the Yard takes pallet QR only · Option B needs a document photo</text>
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
