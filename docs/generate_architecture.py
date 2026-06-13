"""Generate docs/architecture.png — the AgentIQ system architecture diagram.

Pure Pillow (no graphviz/matplotlib needed). Run:  python docs/generate_architecture.py
"""

from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageFont

# --- palette (matches the app theme) ---
BG = "#0f1117"
PANEL = "#161922"
PANEL2 = "#1d212c"
BORDER = "#272c38"
TEXT = "#e6e8ee"
MUTED = "#8b91a1"
AMBER = "#f0a500"
GREEN = "#3fb950"
RED = "#f85149"
BLUE = "#58a6ff"

W, H = 1720, 1240
SCALE = 2  # supersample for crisp text, downscale at the end


def _font(size: int, bold: bool = False, mono: bool = False):
    candidates = (
        ["/System/Library/Fonts/Menlo.ttc"]
        if mono
        else [
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/HelveticaNeue.ttc",
            "/System/Library/Fonts/SFNS.ttf",
        ]
    )
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size * SCALE)
            except Exception:
                continue
    return ImageFont.load_default()


def s(v: int) -> int:
    return v * SCALE


def box(d, x, y, w, h, *, fill=PANEL, outline=BORDER, width=2, radius=14):
    d.rounded_rectangle(
        [s(x), s(y), s(x + w), s(y + h)],
        radius=s(radius),
        fill=fill,
        outline=outline,
        width=s(width),
    )


def text(d, x, y, msg, *, font, fill=TEXT, anchor="la"):
    d.text((s(x), s(y)), msg, font=font, fill=fill, anchor=anchor)


def ctext(d, cx, y, msg, *, font, fill=TEXT):
    d.text((s(cx), s(y)), msg, font=font, fill=fill, anchor="ma")


def arrow(d, x1, y1, x2, y2, *, color=MUTED, width=2, head=11):
    d.line([s(x1), s(y1), s(x2), s(y2)], fill=color, width=s(width))
    ang = math.atan2(y2 - y1, x2 - x1)
    for da in (math.radians(150), math.radians(-150)):
        hx = x2 + head * math.cos(ang + da)
        hy = y2 + head * math.sin(ang + da)
        d.line([s(x2), s(y2), s(hx), s(hy)], fill=color, width=s(width))


def chip(d, x, y, w, h, label, *, font, fill=PANEL2, outline=BORDER, text_fill=TEXT):
    d.rounded_rectangle([s(x), s(y), s(x + w), s(y + h)], radius=s(8), fill=fill, outline=outline, width=s(1))
    ctext(d, x + w / 2, y + h / 2 - 9, label, font=font, fill=text_fill)


def main() -> None:
    img = Image.new("RGB", (W * SCALE, H * SCALE), BG)
    d = ImageDraw.Draw(img)

    f_title = _font(30, bold=True)
    f_h = _font(18, bold=True)
    f = _font(14)
    f_sm = _font(12)
    f_mono = _font(12, mono=True)
    f_lbl = _font(12)

    # --- title ---
    text(d, W / 2, 26, "AgentIQ — System Architecture", font=f_title, fill=TEXT, anchor="ma")
    text(d, W / 2, 66, "Autonomous multi-agent B2B outreach · LangGraph · FastAPI · React",
         font=f_sm, fill=MUTED, anchor="ma")

    LX, RW = 130, 1460  # left x and full row width

    # =====================================================================
    # Layer 1 — Browser
    # =====================================================================
    by = 110
    box(d, LX, by, RW, 130, fill=PANEL)
    text(d, LX + 22, by + 14, "Browser — React + Vite SPA (Zustand, sessionStorage JWT)", font=f_h, fill=TEXT)
    cw = 340
    chip(d, LX + 22, by + 56, cw, 52, "LoginPage  ·  JWT", font=f)
    chip(d, LX + 22 + (cw + 24), by + 56, cw, 52, "DashboardPage  ·  new run", font=f)
    chip(d, LX + 22 + 2 * (cw + 24), by + 56, cw + 60, 52, "RunPage  ·  pipeline + EventFeed + CostBadge + HITLPanel", font=f, text_fill=AMBER)

    # =====================================================================
    # Layer 2 — FastAPI backend
    # =====================================================================
    fy = 300
    box(d, LX, fy, RW, 150, fill=PANEL)
    text(d, LX + 22, fy + 14, "FastAPI Backend  (:8000)", font=f_h, fill=TEXT)
    chip(d, LX + 22, fy + 56, 430, 74,
         "Middleware\nsecurity headers · rate limit · JSON logs · CORS", font=f_sm)
    # multi-line chip needs manual text since chip centers single line
    chip(d, LX + 472, fy + 56, 300, 74, "JWT Auth\n/auth/token · verify_token", font=f_sm)
    chip(d, LX + 792, fy + 56, 690, 74,
         "Routes:  POST /runs · GET /runs/{id}/stream (SSE)\nPOST /runs/{id}/hitl · GET /runs[/{id}]", font=f_mono, text_fill=AMBER)

    # =====================================================================
    # Layer 3 — LangGraph supervisor + pipeline
    # =====================================================================
    gy = 510
    box(d, LX, gy, RW, 300, fill=PANEL, outline=AMBER, width=2)
    text(d, LX + 22, gy + 14, "LangGraph Supervisor  ·  MemorySaver checkpointer", font=f_h, fill=AMBER)

    nodes = ["Researcher", "Analyst", "Drafter", "Evaluator"]
    nw, nh, gap = 250, 80, 60
    nx0 = LX + 40
    ny = gy + 70
    centers = []
    for i, name in enumerate(nodes):
        nx = nx0 + i * (nw + gap)
        box(d, nx, ny, nw, nh, fill=PANEL2, outline=BORDER)
        ctext(d, nx + nw / 2, ny + 16, name, font=f_h, fill=TEXT)
        sub = {
            "Researcher": "Tavily x3 + scrape",
            "Analyst": "ICP fit (0-1)",
            "Drafter": "<=200w + cache",
            "Evaluator": "judge >=0.75",
        }[name]
        ctext(d, nx + nw / 2, ny + 46, sub, font=f_sm, fill=MUTED)
        centers.append((nx, nx + nw / 2, nx + nw))
    for i in range(len(nodes) - 1):
        arrow(d, centers[i][2], ny + nh / 2, centers[i + 1][0], ny + nh / 2, color=AMBER, width=3)

    # decision branch under Evaluator
    ev_cx = centers[3][1]
    branch_y = ny + nh + 40
    # passed -> cost guard -> END
    cg_x = ev_cx + 60
    box(d, cg_x, branch_y, 200, 56, fill=PANEL2, outline=GREEN)
    ctext(d, cg_x + 100, branch_y + 16, "Cost Guard -> END", font=f_sm, fill=GREEN)
    arrow(d, ev_cx, ny + nh, cg_x, branch_y + 10, color=GREEN, width=2)
    text(d, cg_x + 210, branch_y + 16, "passed", font=f_sm, fill=GREEN)

    # failed -> HITL interrupt (to the left/under)
    hitl_x = nx0
    box(d, hitl_x, branch_y, 300, 56, fill=PANEL2, outline=RED)
    ctext(d, hitl_x + 150, branch_y + 16, "HITL interrupt() <-> resume", font=f_sm, fill=RED)
    arrow(d, ev_cx, ny + nh, hitl_x + 300, branch_y + 10, color=RED, width=2)
    text(d, hitl_x + 4, branch_y + 70, "failed -> human review -> Command(resume=...)", font=f_sm, fill=MUTED)

    # =====================================================================
    # Layer 4 — stores + external
    # =====================================================================
    sy = 880
    third = (RW - 2 * 30) / 3
    # Redis
    rx = LX
    box(d, rx, sy, third, 150, fill=PANEL, outline=BLUE)
    text(d, rx + 20, sy + 14, "Redis  (:6379)", font=f_h, fill=BLUE)
    text(d, rx + 20, sy + 52, "live node status + events", font=f_sm, fill=MUTED)
    text(d, rx + 20, sy + 76, "HITL pending payload", font=f_sm, fill=MUTED)
    text(d, rx + 20, sy + 100, "feeds SSE stream (24h TTL)", font=f_sm, fill=MUTED)
    # Supabase
    spx = LX + third + 30
    box(d, spx, sy, third, 150, fill=PANEL, outline=BLUE)
    text(d, spx + 20, sy + 14, "Supabase (Postgres)", font=f_h, fill=BLUE)
    text(d, spx + 20, sy + 52, "runs · outreach_log", font=f_sm, fill=MUTED)
    text(d, spx + 20, sy + 76, "hitl_reviews · eval_results", font=f_sm, fill=MUTED)
    text(d, spx + 20, sy + 100, "persistent audit trail", font=f_sm, fill=MUTED)
    # External
    ex = LX + 2 * (third + 30)
    box(d, ex, sy, third, 150, fill=PANEL, outline=AMBER)
    text(d, ex + 20, sy + 14, "External services", font=f_h, fill=AMBER)
    text(d, ex + 20, sy + 52, "Anthropic Claude (sonnet-4-6)", font=f_sm, fill=MUTED)
    text(d, ex + 20, sy + 76, "Tavily search · web scrape", font=f_sm, fill=MUTED)
    text(d, ex + 20, sy + 100, "Gmail (mock / MCP)", font=f_sm, fill=MUTED)

    # firewall note
    fwy = sy + 160
    box(d, LX, fwy, RW, 44, fill=PANEL2, outline=RED, radius=10)
    ctext(d, LX + RW / 2, fwy + 12, "PromptInjectionGuard (OWASP LLM01/02) scans all user input + scraped content before it enters the pipeline",
          font=f, fill=RED)

    # =====================================================================
    # inter-layer arrows
    # =====================================================================
    midx = LX + RW / 2
    arrow(d, midx - 120, by + 130, midx - 120, fy, color=MUTED, width=2)
    text(d, midx - 110, by + 138, "JWT / REST", font=f_lbl, fill=MUTED)
    arrow(d, midx + 120, fy, midx + 120, by + 130, color=GREEN, width=2)
    text(d, midx + 130, by + 138, "SSE stream", font=f_lbl, fill=GREEN)

    arrow(d, midx, fy + 150, midx, gy, color=MUTED, width=2)
    text(d, midx + 12, fy + 156, "run_pipeline (background task)", font=f_lbl, fill=MUTED)

    # supervisor -> redis / supabase / external
    arrow(d, LX + third / 2, gy + 300, LX + third / 2, sy, color=BLUE, width=2)
    text(d, LX + third / 2 + 8, gy + 306, "events", font=f_lbl, fill=BLUE)
    arrow(d, spx + third / 2, gy + 300, spx + third / 2, sy, color=BLUE, width=2)
    text(d, spx + third / 2 + 8, gy + 306, "persist", font=f_lbl, fill=BLUE)
    arrow(d, ex + third / 2, gy + 300, ex + third / 2, sy, color=AMBER, width=2)
    text(d, ex + third / 2 + 8, gy + 306, "Claude / Tavily / Gmail", font=f_lbl, fill=AMBER)

    out = os.path.join(os.path.dirname(__file__), "architecture.png")
    img = img.resize((W, H), Image.LANCZOS)
    img.save(out)
    print(f"wrote {out}  ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
