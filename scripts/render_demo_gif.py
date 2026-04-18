from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "proxmoxmcp-demo.gif"
WIDTH = 1280
HEIGHT = 720
BG = "#0B1724"
CARD = "#13283E"
CARD_ALT = "#102233"
TEXT = "#F4F8FB"
MUTED = "#B7CBDD"
ACCENT = "#FF7A2F"
GREEN = "#8AE6B8"
BORDER = "#2F526F"


def load_font(name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts") / name,
        Path("/usr/share/fonts/truetype/dejavu") / name,
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


FONT_REG = load_font("segoeui.ttf", 28)
FONT_SMALL = load_font("segoeui.ttf", 20)
FONT_BOLD = load_font("segoeuib.ttf", 36)
FONT_H1 = load_font("segoeuib.ttf", 50)
FONT_MONO = load_font("consola.ttf", 24)


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str, outline: str | None = None, width: int = 1) -> None:
    draw.rounded_rectangle(box, radius=24, fill=fill, outline=outline, width=width)


def text_block(draw: ImageDraw.ImageDraw, x: int, y: int, lines: list[str], font: ImageFont.ImageFont, fill: str, line_gap: int = 8) -> int:
    cur_y = y
    for line in lines:
        draw.text((x, cur_y), line, font=font, fill=fill)
        bbox = draw.textbbox((x, cur_y), line, font=font)
        cur_y = bbox[3] + line_gap
    return cur_y


def base_frame(title: str, subtitle: str) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    draw.ellipse((48, 42, 220, 214), fill="#11283C")
    draw.ellipse((1040, 520, 1230, 710), fill="#11314A")
    draw.text((70, 58), title, font=FONT_H1, fill=TEXT)
    draw.text((72, 118), subtitle, font=FONT_SMALL, fill=MUTED)
    return img


def frame_prompt() -> Image.Image:
    img = base_frame(
        "LLM / AI agent -> Proxmox in one flow",
        "A short homepage demo for Claude Desktop, Open WebUI, MCP, and OpenAPI.",
    )
    draw = ImageDraw.Draw(img)
    rounded(draw, (70, 180, 500, 610), CARD, BORDER, 2)
    rounded(draw, (540, 180, 1210, 610), CARD_ALT, BORDER, 2)
    draw.text((100, 215), "User prompt", font=FONT_BOLD, fill="#FFD4BE")
    prompt = [
        "Create a small Debian test VM on node pve,",
        "snapshot it before changes, then expose",
        "the same control surface over OpenAPI",
        "so I can verify /health.",
    ]
    text_block(draw, 100, 280, prompt, FONT_MONO, TEXT, 12)
    rounded(draw, (100, 465, 270, 515), "#1B4666")
    rounded(draw, (285, 465, 500 - 30, 515), "#1B4666")
    draw.text((125, 477), "Claude Desktop", font=FONT_SMALL, fill="#E7F7FF")
    draw.text((309, 477), "Open WebUI", font=FONT_SMALL, fill="#E7F7FF")
    draw.text((575, 220), "What ProxmoxMCP-Plus does", font=FONT_BOLD, fill="#FFD4BE")
    bullets = [
        "1. Accept the request through MCP.",
        "2. Create / start / snapshot the workload.",
        "3. Expose the same actions over OpenAPI.",
        "4. Return a simple health check for HTTP clients.",
    ]
    text_block(draw, 585, 300, bullets, FONT_REG, TEXT, 14)
    return img


def frame_actions() -> Image.Image:
    img = base_frame(
        "Same server, two ways to use it",
        "MCP for assistants and OpenAPI for dashboards, scripts, and internal tools.",
    )
    draw = ImageDraw.Draw(img)
    rounded(draw, (80, 190, 390, 570), CARD, BORDER, 2)
    rounded(draw, (470, 170, 840, 590), ACCENT, None)
    rounded(draw, (490, 190, 820, 570), "#101E2D", BORDER, 2)
    rounded(draw, (900, 190, 1200, 570), CARD, BORDER, 2)
    draw.text((110, 225), "Input", font=FONT_BOLD, fill="#FFD4BE")
    text_block(draw, 110, 292, ["Claude", "Open WebUI", "Other MCP clients"], FONT_REG, TEXT, 16)
    draw.text((545, 225), "ProxmoxMCP-Plus", font=FONT_BOLD, fill="#FFD4BE")
    text_block(draw, 545, 290, ["VM lifecycle", "LXC lifecycle", "Snapshot / rollback", "Backup / restore", "ISO / template", "SSH-backed container exec"], FONT_REG, TEXT, 16)
    draw.text((930, 225), "Outputs", font=FONT_BOLD, fill="#FFD4BE")
    text_block(draw, 930, 292, ["OpenAPI /docs", "OpenAPI /health", "HTTP automation", "Operator-friendly results"], FONT_REG, TEXT, 16)
    draw.line((390, 380, 470, 380), fill="#FFB997", width=8)
    draw.line((840, 380, 900, 380), fill="#FFB997", width=8)
    return img


def frame_log() -> Image.Image:
    img = base_frame(
        "Live run, not just a feature list",
        "These frames summarize the real lab run that passed in this repository.",
    )
    draw = ImageDraw.Draw(img)
    rounded(draw, (70, 180, 1210, 620), "#091521", BORDER, 2)
    draw.text((100, 215), "Successful live E2E excerpt", font=FONT_BOLD, fill="#FFD4BE")
    lines = [
        "[live-e2e] Creating VM 100",
        "[live-e2e] Starting VM 100",
        "[live-e2e] Creating backup for VM 100",
        "[live-e2e] Restoring VM backup to 101",
        "[live-e2e] Creating container 102",
        "[live-e2e] Executing SSH command inside container 102",
        "[live-e2e] Local OpenAPI health: {\"status\":\"ok\",\"connected_to_mcp\":true}",
        "[live-e2e] Docker OpenAPI health: {\"status\":\"ok\",\"connected_to_mcp\":true}",
        "[live-e2e] Live end-to-end checks completed successfully",
    ]
    text_block(draw, 102, 280, lines, FONT_MONO, GREEN, 12)
    return img


def frame_matrix() -> Image.Image:
    img = base_frame(
        "What has already been proven on a live Proxmox lab",
        "This is the strongest credibility section for the GitHub homepage.",
    )
    draw = ImageDraw.Draw(img)
    rounded(draw, (70, 180, 1210, 615), CARD, BORDER, 2)
    draw.text((100, 220), "Verified paths", font=FONT_BOLD, fill="#FFD4BE")
    rows = [
        "VM create / start / stop / delete",
        "Snapshot create / rollback / delete",
        "Backup / restore",
        "ISO download / delete",
        "LXC create / start / stop / delete",
        "Container SSH-backed execution",
        "OpenAPI /health and schema",
        "Docker build and /health",
    ]
    y = 290
    for row in rows:
        rounded(draw, (100, y - 10, 1160, y + 38), "#0E2234")
        draw.text((125, y), row, font=FONT_REG, fill=TEXT)
        rounded(draw, (1020, y - 2, 1145, y + 34), "#153B2F")
        draw.text((1050, y + 5), "Verified", font=FONT_SMALL, fill=GREEN)
        y += 56
    return img


def frame_health() -> Image.Image:
    img = base_frame(
        "OpenAPI is not an afterthought",
        "The same Proxmox control surface is available to HTTP clients and AI tooling.",
    )
    draw = ImageDraw.Draw(img)
    rounded(draw, (110, 220, 1170, 520), "#091521", BORDER, 2)
    draw.text((145, 255), "HTTP check", font=FONT_BOLD, fill="#FFD4BE")
    text_block(
        draw,
        145,
        330,
        [
            "curl -f http://localhost:8811/health",
            "",
            '{"status":"ok","connected_to_mcp":true}',
            "",
            "curl http://localhost:8811/openapi.json",
            "-> schema available",
        ],
        FONT_MONO,
        GREEN,
        12,
    )
    draw.text((145, 555), "One Proxmox control plane for LLM-native workflows and standard HTTP automation.", font=FONT_REG, fill=TEXT)
    return img


def render() -> None:
    frames = [
        frame_prompt(),
        frame_prompt(),
        frame_actions(),
        frame_actions(),
        frame_log(),
        frame_log(),
        frame_matrix(),
        frame_matrix(),
        frame_health(),
        frame_health(),
    ]
    durations = [1000, 1200, 1000, 1200, 1000, 1300, 1000, 1300, 1000, 1600]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        OUT,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print(OUT)


if __name__ == "__main__":
    render()
