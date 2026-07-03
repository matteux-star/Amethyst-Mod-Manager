"""
Cyberpunk theme — inspired by the Cyberpunk 2077 / Mod Organizer look.

Deep red-black backgrounds, yellow separators, cyan text. Every key mirrors
dark.py — if a key is added there, add it here too or the app breaks when this
theme is selected.
"""

NAME = "Cyberpunk"

# Dark-based custom theme; built-in CTk widgets use the dark appearance.
CTK_APPEARANCE = "dark"

# Signature Cyberpunk colours
#   yellow   #f3e600   (accent / highlights / headers)
#   red      #ff003c   (separators / danger)
#   cyan     #00e5ff   (secondary accent)
#   magenta  #ff2e97   (tertiary)

PALETTE: dict[str, str | tuple] = {
    # Backgrounds — deep red-black
    "BG_DEEP":       "#120608",
    "BG_PANEL":      "#1a080b",
    "BG_HEADER":     "#200a0e",
    "BG_ROW":        "#160709",
    "BG_ROW_ALT":    "#1e0a0e",
    "BG_ROW_HOVER":  "#331016",
    "BG_LIST":       "#120607",
    "BG_SEP":        "#e6d200",   # bright yellow separator bar
    "BG_HOVER":      "#4a0012",
    "BG_SELECT":     "#5c0018",   # dark red glow selection (matches screenshot)
    "BG_HOVER_ROW":  "#331016",

    # Accents — electric yellow
    "ACCENT":        "#f3e600",
    "ACCENT_HOV":    "#fff340",
    "TEXT_ON_ACCENT":"#0a0e12",   # dark text reads on bright yellow

    # Text — cyan family
    "TEXT_MAIN":     "#7cf0ff",
    "TEXT_DIM":      "#4a8f9c",
    "TEXT_MUTED":    "#66c2d4",
    "TEXT_FAINT":    "#3d7580",
    "TEXT_SEP":      "#1a1200",   # dark text on the bright yellow bar
    "TEXT_WHITE":    "#aef4ff",   # "white" text reads as cyan in this theme
    "TEXT_BLACK":    "#000000",
    "TEXT_OK":       "#5ce6b0",
    "TEXT_ERR":      "#ff4d6a",
    "TEXT_WARN":     "#f3e600",
    "TEXT_OK_BRIGHT":   "#3ef0a0",
    "TEXT_ERR_BRIGHT":  "#ff3355",
    "TEXT_WARN_BRIGHT": "#ffdb2e",

    # Borders
    "BORDER":        "#243541",
    "BORDER_DIM":    "#2e4451",
    "BORDER_FAINT":  "#3a5262",

    # Buttons — reds
    "RED_BTN":       "#c00028",
    "RED_HOV":       "#ff003c",
    "BTN_DANGER":        "#c00028",
    "BTN_DANGER_HOV":    "#ff003c",
    "BTN_DANGER_ALT":    "#8b0020",
    "BTN_DANGER_ALT_HOV":"#c00028",
    "BTN_DANGER_DEEP":   "#6a0018",
    "BTN_DANGER_DEEP_HOV":"#970022",
    "BTN_CANCEL":        "#c00028",
    "BTN_CANCEL_HOV":    "#970022",

    # Buttons — greens (teal-leaning to fit the palette)
    "BTN_SUCCESS":          "#008a5e",
    "BTN_SUCCESS_HOV":      "#00b878",
    "BTN_SUCCESS_ALT":      "#0a7a56",
    "BTN_SUCCESS_ALT_HOV":  "#10a071",
    "BTN_SUCCESS_DEEP":     "#0a6b4c",
    "BTN_SUCCESS_DEEP_HOV": "#109065",

    # Buttons — oranges/yellows
    "BTN_WARN":          "#c9a400",
    "BTN_WARN_HOV":      "#f3e600",
    "BTN_WARN_DEEP":     "#7a6400",
    "BTN_WARN_DEEP_HOV": "#a08600",
    "BTN_WARN_BROWN":    "#5a4a00",
    "BTN_WARN_BROWN_HOV":"#7a6400",
    "BTN_WARN_ORANGE":   "#b37000",
    "BTN_WARN_ORANGE_HOV":"#d99000",

    # Buttons — blues/cyans
    "BTN_INFO":          "#0a5a7a",
    "BTN_INFO_HOV":      "#0d84b0",
    "BTN_INFO_DEEP":     "#0a5a8a",
    "BTN_INFO_DEEP_HOV": "#00a0d0",
    "BTN_NEUTRAL":       "#1a4a6a",
    "BTN_NEUTRAL_HOV":   "#2a6a94",

    # Buttons — greys
    "BTN_GREY":        "#1e2c36",
    "BTN_GREY_HOV":    "#2a3d4a",
    "BTN_GREY_ALT":    "#182430",
    "BTN_GREY_ALT_HOV":"#243541",

    # Buttons — purples/magenta
    "BTN_PURPLE":     "#c0007a",
    "BTN_PURPLE_HOV": "#ff2e97",

    # Tree tags
    "TAG_FOLDER":       "#00e5ff",
    "TAG_BSA":          "#f3e600",
    "TAG_BSA_ALT":      "#00e5ff",
    "TAG_INI_PROFILE":  "#00e5ff",
    "TAG_BUNDLED_FG":   "#66d9ff",
    "TAG_BUNDLED_BG":   "#0a2833",
    "TAG_INSTALLED_BG": "#0a3a2a",
    "TAG_UNORDERED_FG": "#6d7d88",

    # Tones
    "TONE_GREEN":     "#5ce6b0",
    "TONE_RED":       "#ff4d6a",
    "TONE_BLUE":      "#00e5ff",
    "TONE_CYAN":      "#00e5ff",
    "TONE_BLUE_SOFT": "#66d9ff",
    "TONE_FLAG":      "#f3e600",

    # Scrollbars
    "SCROLL_BG":     "#1c2733",
    "SCROLL_TROUGH": "#0a0e12",
    "SCROLL_ACTIVE": "#f3e600",

    # Overlays / special
    "BG_OVERLAY_ERR":  "#180810",
    "BG_OVERLAY_DEEP": "#0a0e12",
    "BG_CARD":         "#141b22",
    "BG_CARD_ALT":     "#0f1419",
    "BG_GREEN_ROW":    "#0a4a34",
    "BG_GREEN_DEEP":   "#0a3a28",
    "BG_RED_DEEP":     "#4a0a18",
    "BG_ORANGE_DEEP":  "#4a3a00",
    "BG_GREEN_TEXT":   "#a8ffe0",
    "BG_RED_TEXT":     "#ffc8d2",
    "BG_ORANGE_TEXT":  "#fff0a0",
    "BG_BLUE_DEEP":    "#0a2a4a",
    "BG_BLUE_TEXT":    "#a0e8ff",
    "BG_DARK_BLUE":    "#0a1220",
    "BG_DARK_GREEN":   "#0a1a14",
    "BG_ENTRY":        "#0a0f14",
    "BG_BTN_SAVE":     "#1a4a6a",
    "BG_SELECT_BAR":   "#2a1020",
    "BG_MOD_REQ":      "#008a5e",
    "BG_MOD_OPT":      "#c9a400",

    # Status
    "STATUS_ERR_BRIGHT":    "#ff3355",
    "STATUS_BADGE_RED":     "#ff003c",
    "STATUS_BADGE_GREEN":   "#00b878",
    "STATUS_SUCCESS_SOLID": "#00ffaa",
    "STATUS_QUEUED":        "#f3e600",
    "STATUS_DL_GREEN":      "#00e090",

    # Card text — cyan family
    "TEXT_CARD":     "#8fe4f0",
    "TEXT_CARD_DIM": "#3d7580",
    "TEXT_CARD_MED": "#a8ecf6",
    "TEXT_TREE_FG":  "#3ef0a0",

    # CTk light/dark tuples — keep tuples so built-in CTk widgets still adapt.
    "CTK_TEXT":       ("#000000", "#FFFFFF"),
    "CTK_FOOTER_FG":  ("#EBECF0", "#12171D"),
    "CTK_FOOTER_HOV": ("#DFE1E5", "#1C2733"),
    "CTK_SEP":        ("#C9CCD6", "#243541"),
    "CTK_SEP_ALT":    ("#D0D0D0", "#2E4451"),
    "CTK_BTN_HOVER":  ("gray90", "gray20"),

    # Misc
    "LINK_BLUE":     "#00e5ff",
}
