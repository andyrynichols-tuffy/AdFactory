"""Font lookup shared by the editor (font list) and renderer (caption images)."""
from pathlib import Path

from .config import FONTS_DIR

WIN_FONTS = Path("C:/Windows/Fonts")
EMOJI_FONT = WIN_FONTS / "seguiemj.ttf"

# Common Windows fonts with a meme/TikTok feel. Any .ttf/.otf dropped into
# fonts/ is offered too (name = file name without extension).
SYSTEM_FONTS = {
    "Impact": "impact.ttf", "Arial Black": "ariblk.ttf", "Arial": "arialbd.ttf",
    "Comic Sans MS": "comicbd.ttf", "Segoe UI Black": "seguibl.ttf", "Segoe UI": "segoeuib.ttf",
    "Segoe UI Semibold": "seguisb.ttf", "Segoe UI Regular": "segoeui.ttf",
    "Bahnschrift": "bahnschrift.ttf", "Georgia": "georgiab.ttf", "Courier New": "courbd.ttf",
    "Trebuchet MS": "trebucbd.ttf", "Verdana": "verdanab.ttf", "Times New Roman": "timesbd.ttf",
    "Ink Free": "inkfree.ttf", "Segoe Print": "segoeprb.ttf", "Gabriola": "gabriola.ttf",
    "Showcard Gothic": "showg.ttf", "Cooper Black": "coopbl.ttf", "Stencil": "stencil.ttf",
    "Chiller": "chiller.ttf", "Jokerman": "jokerman.ttf", "Broadway": "broadw.ttf",
    "Bodoni MT Black": "BOD_BLAR.TTF", "Bodoni MT Bold": "BOD_B.TTF", "Bodoni MT": "BOD_R.TTF",
    "Bodoni MT Condensed Bold": "BOD_CB.TTF",
    "Century Gothic": "GOTHIC.TTF", "Century Gothic Bold": "GOTHICB.TTF",
    "Tw Cen MT": "TCM_____.TTF", "Tw Cen MT Bold": "TCB_____.TTF",
    "Copperplate Gothic Light": "COPRGTL.TTF", "Copperplate Gothic Bold": "COPRGTB.TTF",
    "Gill Sans MT": "GIL_____.TTF", "Gill Sans MT Bold": "GILB____.TTF",
}


def custom_fonts() -> dict:
    return {p.stem: p for p in sorted(FONTS_DIR.glob("*")) if p.suffix.lower() in (".ttf", ".otf")}


def available() -> dict:
    return {
        "system": [n for n, f in SYSTEM_FONTS.items() if (WIN_FONTS / f).exists()],
        "custom": [{"name": n, "url": f"/fonts/{p.name}"} for n, p in custom_fonts().items()],
    }


def font_file(name: str) -> Path:
    custom = custom_fonts()
    if name in custom:
        return custom[name]
    f = WIN_FONTS / SYSTEM_FONTS.get(name, "arialbd.ttf")
    return f if f.exists() else WIN_FONTS / "arial.ttf"
