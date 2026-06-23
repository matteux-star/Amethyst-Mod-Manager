"""
plugin_loader.py
Discovers and loads external wizard plugin scripts from the Plugins directory.

Plugin files are plain Python scripts placed in ~/.config/AmethystModManager/Plugins/.
Each must define a module-level ``PLUGIN_INFO`` dict and a dialog class that follows
the standard wizard dialog signature::

    PLUGIN_INFO = {
        "id":           "my_tool",
        "label":        "My Tool",
        "description":  "One-line description.",
        "game_ids":     ["skyrim_se"],      # list of supported game_ids
        "all_games":    False,              # True = show for every game
        "dialog_class": "MyToolDialog",     # class name in this file
        "category":     "Patchers & Cleanup",  # optional: picker group header.
                                                # Omit to auto-infer; a new name
                                                # not in CATEGORY_ORDER is shown
                                                # automatically, before "Other".
    }

    class MyToolDialog(ctk.CTkFrame):
        def __init__(self, parent, game, log_fn=None, *, on_close=None, **extra):
            ...

Bad or incomplete plugin files are silently skipped so one broken plugin
doesn't affect the rest of the application.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from Games.base_game import BaseGame, WizardTool
from Utils.config_paths import get_plugins_dir

# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------

_plugins_cache: list[dict] = []
_plugins_dir_mtime: float = 0.0

_REQUIRED_KEYS = {"id", "label", "dialog_class"}


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_plugins(*, force: bool = False) -> list[dict]:
    """Scan the Plugins directory and return validated plugin descriptors.

    Each descriptor is the plugin's ``PLUGIN_INFO`` dict augmented with:
      - ``_resolved_class``: the actual dialog class object
      - ``_source_file``:    path to the ``.py`` file

    Results are cached and only re-scanned when the directory's mtime changes,
    unless *force* is ``True``.
    """
    global _plugins_cache, _plugins_dir_mtime

    plugins_dir = get_plugins_dir()

    try:
        current_mtime = plugins_dir.stat().st_mtime
    except OSError:
        return _plugins_cache

    if not force and current_mtime == _plugins_dir_mtime and _plugins_cache:
        return _plugins_cache

    plugins: list[dict] = []
    seen_ids: set[str] = set()

    for py_file in sorted(plugins_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            plugin = _load_plugin_file(py_file)
        except Exception as exc:
            _warn(f"Plugin '{py_file.name}': skipped — {exc}")
            continue

        if plugin is None:
            continue

        pid = plugin["id"]
        if pid in seen_ids:
            _warn(f"Plugin '{py_file.name}': duplicate id '{pid}', skipped.")
            continue

        seen_ids.add(pid)
        plugins.append(plugin)

    _plugins_cache = plugins
    _plugins_dir_mtime = current_mtime
    return plugins


def _load_plugin_file(py_file: Path) -> dict | None:
    """Load a single plugin file and return a validated descriptor, or *None*."""
    module_name = f"_amm_plugins.{py_file.stem}"

    spec = importlib.util.spec_from_file_location(module_name, str(py_file))
    if spec is None or spec.loader is None:
        return None

    # Remove previously cached module so updated files are re-executed
    sys.modules.pop(module_name, None)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    info = getattr(module, "PLUGIN_INFO", None)
    if not isinstance(info, dict):
        _warn(f"Plugin '{py_file.name}': missing or invalid PLUGIN_INFO dict.")
        return None

    missing = _REQUIRED_KEYS - info.keys()
    if missing:
        _warn(f"Plugin '{py_file.name}': PLUGIN_INFO missing keys: {missing}")
        return None

    class_name = info["dialog_class"]
    cls = getattr(module, class_name, None)
    if cls is None or not isinstance(cls, type):
        _warn(f"Plugin '{py_file.name}': dialog_class '{class_name}' not found or not a class.")
        return None

    descriptor = dict(info)
    descriptor["_resolved_class"] = cls
    descriptor["_source_file"] = py_file
    descriptor.setdefault("description", "")
    descriptor.setdefault("game_ids", [])
    descriptor.setdefault("all_games", False)
    return descriptor


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_plugin_tools_for_game(game_id: str) -> list[WizardTool]:
    """Return :class:`WizardTool` entries from loaded plugins that match *game_id*."""
    tools: list[WizardTool] = []
    for plugin in discover_plugins():
        if plugin.get("all_games") or game_id in plugin.get("game_ids", []):
            tools.append(WizardTool(
                id=plugin["id"],
                label=plugin["label"],
                description=plugin.get("description", ""),
                dialog_class_path="",
                category=plugin.get("category", ""),
                extra={"_dialog_class": plugin["_resolved_class"]},
            ))
    return tools


def get_all_wizard_tools(game: BaseGame) -> list[WizardTool]:
    """Return built-in wizard tools merged with external plugin tools for *game*."""
    return list(game.wizard_tools) + get_plugin_tools_for_game(game.game_id)


# ---------------------------------------------------------------------------
# Exe → wizard mapping
# ---------------------------------------------------------------------------
#
# When a user runs one of these executables from the exe dropdown, the matching
# wizard tool is opened instead of launching the exe directly through Proton.
# The wizards handle install/deploy/prefix setup that a bare Proton launch skips.
#
# Keyed by the tool's ``dialog_class_path``; the value is the set of exe
# basenames (lowercase) the wizard launches.  Tools whose exe name varies per
# game (the xEdit family) are handled dynamically below via ``extra`` instead.

_WIZARD_CLASS_EXES: dict[str, set[str]] = {
    "wizards.pandora.PandoraWizard": {"pandora behaviour engine+.exe"},
    "wizards.bodyslide.BodySlideWizard": {"bodyslide.exe", "bodyslide x64.exe"},
    "wizards.bodyslide.OutfitStudioWizard": {"outfitstudio.exe", "outfitstudio x64.exe"},
    "wizards.pgpatcher.PGPatcherWizard": {"pgpatcher.exe"},
    "wizards.eslifier.ESLifierWizard": {"eslifier.exe"},
    "wizards.dyndolod.TexGenWizard": {"texgenx64.exe"},
    "wizards.dyndolod.DynDOLODWizard": {"dyndolodx64.exe"},
    "wizards.dyndolod.xLODGenWizard": {"xlodgenx64.exe", "xlodgen.exe"},
    "wizards.bethini.BethINIWizard": {"bethini.exe"},
    "wizards.wrye_bash.WryeBashWizard": {"wrye bash.exe"},
    "wizards.script_merger_tw3.ScriptMergerWizard": {"witcherscriptmerger.exe"},
}


def _tool_exe_names(tool: WizardTool) -> set[str]:
    """Return the lowercase exe basenames that *tool* launches, if any.

    Covers the static class→exe registry plus the parametrised xEdit family,
    whose exe name is supplied per-game via ``extra['xedit_exe']`` (with a
    ``QuickAutoClean`` variant for the QAC wizard).
    """
    path = tool.dialog_class_path
    if path in _WIZARD_CLASS_EXES:
        return _WIZARD_CLASS_EXES[path]
    if path in ("wizards.sseedit.SSEEditWizard", "wizards.sseedit.SSEEditQACWizard"):
        base = (tool.extra.get("xedit_exe") or "SSEEdit.exe")
        if path.endswith("QACWizard") and base.lower().endswith(".exe"):
            base = base[: -len(".exe")] + "QuickAutoClean.exe"
        return {base.lower()}
    return set()


def wizard_tool_for_exe(game: BaseGame, exe_name: str) -> WizardTool | None:
    """Return the wizard tool that should open when *exe_name* is run, or None.

    *exe_name* is matched case-insensitively against the exe basenames each of
    *game*'s available wizard tools launches.  The plain xEdit wizard is
    preferred over its QuickAutoClean sibling when both could match.
    """
    target = exe_name.lower()
    qac_match: WizardTool | None = None
    for tool in get_all_wizard_tools(game):
        if target in _tool_exe_names(tool):
            if tool.dialog_class_path.endswith("QACWizard"):
                qac_match = tool
            else:
                return tool
    return qac_match


# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------

def _warn(msg: str) -> None:
    """Log a plugin warning via the app log if available, otherwise print."""
    try:
        from Utils.app_log import app_log
        app_log(msg)
    except Exception:
        print(f"[plugin_loader] {msg}")
