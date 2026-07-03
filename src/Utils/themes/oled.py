"""
OLED theme — the default dark theme with pure-black backgrounds.

Identical to dark.py except every background / surface colour is flattened to
pure black (#000000) or a near-black so OLED panels save power and read as true
black. Text, accents and button colours are kept for contrast/readability.

Every key here must also exist in every other theme file. If you add a new
constant, add it to every theme or the app will break when that theme is
selected.
"""

NAME = "OLED"

CTK_APPEARANCE = "dark"

PALETTE: dict[str, str | tuple] = {
    # Backgrounds — pure black surfaces
    "BG_DEEP":       "#000000",
    "BG_PANEL":      "#000000",
    "BG_HEADER":     "#050505",
    "BG_ROW":        "#000000",
    "BG_ROW_ALT":    "#0a0a0a",
    "BG_ROW_HOVER":  "#1a1a1a",
    "BG_LIST":       "#000000",
    "BG_SEP":        "#141414",   # overridden via load_theme_colors
    "BG_HOVER":      "#062033",
    "BG_SELECT":     "#0a4a7a",
    "BG_HOVER_ROW":  "#1a1a1a",

    # Accents
    "ACCENT":        "#0078d4",
    "ACCENT_HOV":    "#1084d8",
    "TEXT_ON_ACCENT":"#ffffff",

    # Text
    "TEXT_MAIN":     "#d4d4d4",
    "TEXT_DIM":      "#858585",
    "TEXT_MUTED":    "#aaaaaa",
    "TEXT_FAINT":    "#888888",
    "TEXT_SEP":      "#b0b0b0",
    "TEXT_WHITE":    "#ffffff",
    "TEXT_BLACK":    "#000000",
    "TEXT_OK":       "#98c379",
    "TEXT_ERR":      "#e06c75",
    "TEXT_WARN":     "#e5c07b",
    "TEXT_OK_BRIGHT":   "#6bc76b",
    "TEXT_ERR_BRIGHT":  "#e06c6c",
    "TEXT_WARN_BRIGHT": "#e5a04a",

    # Borders — darker so black stays black
    "BORDER":        "#2a2a2a",
    "BORDER_DIM":    "#333333",
    "BORDER_FAINT":  "#3d3d3d",

    # Buttons — reds
    "RED_BTN":       "#a83232",
    "RED_HOV":       "#c43c3c",
    "BTN_DANGER":        "#b33a3a",
    "BTN_DANGER_HOV":    "#c94848",
    "BTN_DANGER_ALT":    "#8b1a1a",
    "BTN_DANGER_ALT_HOV":"#b22222",
    "BTN_DANGER_DEEP":   "#7a1a1a",
    "BTN_DANGER_DEEP_HOV":"#a02020",
    "BTN_CANCEL":        "#c0392b",
    "BTN_CANCEL_HOV":    "#a93226",

    # Buttons — greens
    "BTN_SUCCESS":          "#2d7a2d",
    "BTN_SUCCESS_HOV":      "#3a9e3a",
    "BTN_SUCCESS_ALT":      "#2e6b30",
    "BTN_SUCCESS_ALT_HOV":  "#3a8a3d",
    "BTN_SUCCESS_DEEP":     "#2a6e3f",
    "BTN_SUCCESS_DEEP_HOV": "#369150",

    # Buttons — oranges
    "BTN_WARN":          "#c37800",
    "BTN_WARN_HOV":      "#e28b00",
    "BTN_WARN_DEEP":     "#7a5a00",
    "BTN_WARN_DEEP_HOV": "#a07800",
    "BTN_WARN_BROWN":    "#5a3a00",
    "BTN_WARN_BROWN_HOV":"#7a5200",
    "BTN_WARN_ORANGE":   "#b35a00",
    "BTN_WARN_ORANGE_HOV":"#d97000",

    # Buttons — blues
    "BTN_INFO":          "#1e4d7a",
    "BTN_INFO_HOV":      "#2a6aab",
    "BTN_INFO_DEEP":     "#1a5a8a",
    "BTN_INFO_DEEP_HOV": "#2070a8",
    "BTN_NEUTRAL":       "#3a5a8a",
    "BTN_NEUTRAL_HOV":   "#4a70aa",

    # Buttons — greys (darkened for OLED)
    "BTN_GREY":        "#1f1f1f",
    "BTN_GREY_HOV":    "#2e2e2e",
    "BTN_GREY_ALT":    "#1a1a1a",
    "BTN_GREY_ALT_HOV":"#2a2a2a",

    # Buttons — purples
    "BTN_PURPLE":     "#7b2fa8",
    "BTN_PURPLE_HOV": "#9b3fd0",

    # Tree tags
    "TAG_FOLDER":       "#56b6c2",
    "TAG_BSA":          "#d8a657",
    "TAG_BSA_ALT":      "#56d8e4",
    "TAG_INI_PROFILE":  "#00e5ff",
    "TAG_BUNDLED_FG":   "#7ab8e8",
    "TAG_BUNDLED_BG":   "#0a1520",
    "TAG_INSTALLED_BG": "#0f2a0f",
    "TAG_UNORDERED_FG": "#888888",

    # Tones
    "TONE_GREEN":     "#98c379",
    "TONE_RED":       "#e06c75",
    "TONE_BLUE":      "#61afef",
    "TONE_CYAN":      "#7ec8e3",
    "TONE_BLUE_SOFT": "#7aa2f7",
    "TONE_FLAG":      "#e5c07b",

    # Scrollbars — dark trough on black
    "SCROLL_BG":     "#242424",
    "SCROLL_TROUGH": "#000000",
    "SCROLL_ACTIVE": "#0078d4",

    # Overlays / special
    "BG_OVERLAY_ERR":  "#0a0a14",
    "BG_OVERLAY_DEEP": "#000000",
    "BG_CARD":         "#141414",
    "BG_CARD_ALT":     "#0d0d0d",
    "BG_GREEN_ROW":    "#0f3a0f",
    "BG_GREEN_DEEP":   "#0f330f",
    "BG_RED_DEEP":     "#330f0f",
    "BG_ORANGE_DEEP":  "#3a260d",
    "BG_GREEN_TEXT":   "#c8ffc8",
    "BG_RED_TEXT":     "#ffc8c8",
    "BG_ORANGE_TEXT":  "#ffe0b0",
    "BG_BLUE_DEEP":    "#0f2740",
    "BG_BLUE_TEXT":    "#b0d8ff",
    "BG_DARK_BLUE":    "#0a0a14",
    "BG_DARK_GREEN":   "#0a140a",
    "BG_ENTRY":        "#000000",
    "BG_BTN_SAVE":     "#2e2e5a",
    "BG_SELECT_BAR":   "#20203a",
    "BG_MOD_REQ":      "#2d7a2d",
    "BG_MOD_OPT":      "#c37800",

    # Status
    "STATUS_ERR_BRIGHT":    "#ff6b6b",
    "STATUS_BADGE_RED":     "#e74c3c",
    "STATUS_BADGE_GREEN":   "#2a8c2a",
    "STATUS_SUCCESS_SOLID": "#00ff88",
    "STATUS_QUEUED":        "#ff9a3c",
    "STATUS_DL_GREEN":      "#4caf50",

    # Card text
    "TEXT_CARD":     "#cccccc",
    "TEXT_CARD_DIM": "#777777",
    "TEXT_CARD_MED": "#dddddd",
    "TEXT_TREE_FG":  "#6dbf6d",

    # CTk light/dark tuples — dark value pushed to black.
    "CTK_TEXT":       ("#000000", "#FFFFFF"),
    "CTK_FOOTER_FG":  ("#EBECF0", "#000000"),
    "CTK_FOOTER_HOV": ("#DFE1E5", "#1a1a1a"),
    "CTK_SEP":        ("#C9CCD6", "#2a2a2a"),
    "CTK_SEP_ALT":    ("#D0D0D0", "#242424"),
    "CTK_BTN_HOVER":  ("gray90", "gray15"),

    # Misc
    "LINK_BLUE":     "#3574F0",
}
