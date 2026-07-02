"""
Qt wizard-tool registry + shared Qt wizard views.

Games keep declaring their tools as ``WizardTool`` descriptors (see
``Games.base_game``) whose ``dialog_class_path`` points at the Tk wizard
class.  The Qt app never imports those Tk classes — instead this registry maps
each ``dialog_class_path`` to a Qt view factory.  Tools without an entry here
appear greyed out in the Wizards header menu until their port lands; tools in
``EXCLUDED`` are dropped from the Qt app entirely.

Layout convention (mirrors the Tk side, where shared wizards live in
``wizards/`` and game-specific ones inside their game's folder):
  * multi-game Qt views live in THIS package (``wizards_qt/``);
  * game-specific Qt views live next to their Tk counterpart in the game's
    folder, as ``Games/<Game>/<name>_wizard_qt.py``.
Both kinds are registered here.  Factories lazy-import their view module, so
the Tk app never pulls in Qt code and game-folder views only load on open.

Views open as panel-scoped tabs: ``panel`` picks which panel the tab takes
over ("plugins" for most tools, "modlist" for the wide ones that were
full-width overlays in Tk).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


@dataclass(frozen=True)
class QtWizardSpec:
    """One ported wizard: how to build its view and which panel it scopes to."""
    # (game, log_fn=..., on_close=..., ctx=QtWizardContext, **extra) -> QWidget
    view_factory: Callable[..., "QWidget"]
    panel: str = "plugins"                  # "plugins" | "modlist"


@dataclass(frozen=True)
class QtWizardContext:
    """App hooks handed to every wizard view (factories that don't need them
    just ignore the ctx kwarg).

    run_deploy(on_done) starts a deploy through the app's deploy machinery
    (mutex/coalesce + progress popup); on_done(ok: bool) fires on the UI
    thread when the final deploy completes. Returns False if a deploy could
    not be started. refresh_modlist() re-syncs the mods folder + reloads the
    panels (footer Refresh).
    """
    profile_name: str = "default"
    run_deploy: Callable | None = None
    refresh_modlist: Callable | None = None


# Deliberately dropped from the Qt app (not even shown greyed out).
EXCLUDED: frozenset[str] = frozenset({
    "wizards.dtkit_patch.DtkitPatchWizard",
})


def _re_pak_restore(game, log_fn=None, on_close=None, ctx=None, **extra):
    # Lazy import keeps app startup light (matches app.py local-import style).
    from wizards_qt.re_pak_restore_view import RePakRestoreView
    return RePakRestoreView(game, log_fn=log_fn, on_close=on_close, **extra)


def _pandora(game, log_fn=None, on_close=None, ctx=None, **extra):
    from wizards_qt.pandora_view import PandoraView
    return PandoraView(game, log_fn=log_fn, on_close=on_close, ctx=ctx)


def _reshade(game, log_fn=None, on_close=None, ctx=None, **extra):
    # extra carries reshade_dll / reshade_arch from the WizardTool registration.
    from wizards_qt.reshade_view import ReShadeView
    return ReShadeView(game, log_fn=log_fn, on_close=on_close, ctx=ctx, **extra)


def _script_extender(game, log_fn=None, on_close=None, ctx=None, **extra):
    # extra carries github_api_url / download_url / direct_download_url /
    # archive_keywords / versions from each game's WizardTool registration.
    from wizards_qt.script_extender_view import ScriptExtenderView
    return ScriptExtenderView(game, log_fn=log_fn, on_close=on_close,
                              ctx=ctx, **extra)


# dialog_class_path → QtWizardSpec.  Keyed by the Tk class path (not tool.id,
# which is per-game suffixed like "run_skygen_skyrimse") so one entry serves
# every game that registers the tool.
REGISTRY: dict[str, QtWizardSpec] = {
    "wizards.re_pak_restore.RePakRestoreWizard": QtWizardSpec(_re_pak_restore),
    "wizards.pandora.PandoraWizard": QtWizardSpec(_pandora),
    "wizards.reshade.ReShadeWizard": QtWizardSpec(_reshade),
    "wizards.script_extender.ScriptExtenderWizard": QtWizardSpec(_script_extender),
}


def get_spec(dialog_class_path: str) -> QtWizardSpec | None:
    return REGISTRY.get(dialog_class_path)
