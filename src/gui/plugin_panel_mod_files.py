"""
Mod Files tab mixin for PluginPanel.

Owns the per-mod file tree:
- Tab construction with checkbox columns (Top Level, Disable).
- Single-mod editing view + read-only separator view.
- Strip-prefix promotion / demotion via the Top Level column.
- Per-row exclusion via the Disable column (writes ``excluded_mod_files``).
- Right-click → Open in File Browser.

Host (PluginPanel) owns: ``self._game``, ``self._tabs``, ``self._log``,
``self._safe_after``, the mod-files state attributes initialised in
``PluginPanel.__init__`` (``_mod_files_mod_name``, ``_mod_files_index_path``,
``_mod_files_profile_dir``, ``_mod_files_excluded``, ``_mod_files_on_change``,
``_plugin_order_on_change``, ``_mf_only_conflicts_var``), the Pack/Unpack
button click handlers ``_on_pack_bsa_click`` / ``_on_unpack_bsa_click`` /
``_update_pack_bsa_button_state``, the shared helpers ``_get_conflict_cache``,
``_show_simple_context_menu``, ``_get_staging_path``, ``_open_folder_in_browser``.
"""

import tkinter as tk
import tkinter.ttk as ttk
from pathlib import Path

import customtkinter as ctk
from PIL import Image as PilImage, ImageTk

import gui.theme as _theme
from gui.theme import (
    ACCENT,
    ACCENT_HOV,
    BG_DEEP,
    BG_HEADER,
    BG_HOVER,
    BG_LIST,
    BG_PANEL,
    BORDER,
    BTN_SUCCESS,
    BTN_SUCCESS_HOV,
    RED_BTN,
    RED_HOV,
    TEXT_DIM,
    TEXT_MAIN,
    SCROLL_BG,
    SCROLL_TROUGH,
    SCROLL_ACTIVE,
    scaled,
)
from gui.wheel_compat import LEGACY_WHEEL_REDUNDANT
from Utils.profile_state import (
    read_excluded_mod_files,
    write_excluded_mod_files,
    read_mod_strip_prefixes,
    write_mod_strip_prefixes,
)
from Utils.filemap import OVERWRITE_NAME as _OVERWRITE_NAME


class PluginPanelModFilesMixin:
    """Per-mod file tree with Top Level + Disable checkbox columns."""

    # Checkbox rendering helpers
    _MF_CHECK   = "☑"
    _MF_UNCHECK = "☐"
    _MF_PARTIAL = "☒"   # folder with some excluded children
    _MF_TL_SEL   = "☑"   # path marked as top-level (stripped on deploy)
    _MF_TL_UNSEL = "☐"   # path not marked

    def _build_mod_files_tab(self):
        tab = self._tabs.tab("Mod Files")
        tab.configure(fg_color=BG_LIST)
        tab.grid_rowconfigure(1, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_columnconfigure(1, weight=0)

        # Toolbar
        toolbar = tk.Frame(tab, bg=BG_HEADER, height=scaled(28), highlightthickness=0)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        toolbar.grid_propagate(False)

        self._mf_tree_expanded: bool = False
        self._mf_expand_btn = tk.Button(
            toolbar, text="⊞ Expand All",
            bg=BG_PANEL, fg=TEXT_MAIN, activebackground=BG_HOVER,
            relief="flat", font=(_theme.FONT_FAMILY, _theme.FS10),
            bd=0, cursor="hand2", highlightthickness=0,
            command=self._toggle_mf_tree_expand,
        )
        self._mf_expand_btn.pack(side="right", padx=(0, 8), pady=2)

        self._mf_only_conflicts_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            toolbar, text="Show only conflicts",
            variable=self._mf_only_conflicts_var,
            width=140, height=20,
            checkbox_width=16, checkbox_height=16,
            font=("Cantarell", _theme.FS10),
            text_color=TEXT_MAIN,
            fg_color=ACCENT, hover_color=ACCENT_HOV,
            border_color=BORDER, checkmark_color="white",
            bg_color=BG_HEADER,
            command=lambda: self._mf_refresh_current_view(),
        ).pack(side="right", padx=(0, 8), pady=2)

        self._mod_files_label = tk.Label(
            toolbar, text="(no mod selected)",
            bg=BG_HEADER, fg=TEXT_DIM,
            font=(_theme.FONT_FAMILY, _theme.FS10),
            anchor="w",
        )
        self._mod_files_label.pack(side="left", padx=8, pady=4, fill="x", expand=True)

        # Treeview — styled to match CTkTreeview / Data tab.
        # Flatpak: use default Treeitem.indicator (custom has broken state handling).
        # AppImage / native: use custom arrow images.
        from gui.ctk_components import _is_flatpak_sandbox
        style = ttk.Style()
        style.theme_use("default")
        use_default_indicator = _is_flatpak_sandbox()
        if not use_default_indicator:
            from gui.ctk_components import ICON_PATH as _ICON_PATH, _load_icon_image as _load_iim
            _im_open = _load_iim(_ICON_PATH.get("arrow"))
            _im_close = _im_open.rotate(90)
            _im_empty = PilImage.new("RGB", (15, 15), BG_DEEP)
            _img_open_mf = ImageTk.PhotoImage(_im_open, name="img_open_mf", size=(15, 15))
            _img_close_mf = ImageTk.PhotoImage(_im_close, name="img_close_mf", size=(15, 15))
            _img_empty_mf = ImageTk.PhotoImage(_im_empty, name="img_empty_mf", size=(15, 15))
            self._mf_arrow_images = (_img_open_mf, _img_close_mf, _img_empty_mf)
            try:
                style.element_create("Treeitem.mfindicator", "image", "img_close_mf",
                    ("user1", "img_open_mf"), ("user2", "img_empty_mf"),
                    sticky="w", width=15, height=15)
            except Exception:
                pass
        try:
            indicator_elem = "Treeitem.indicator" if use_default_indicator else "Treeitem.mfindicator"
            style.layout("ModFiles.Treeview.Item", [
                ("Treeitem.padding", {"sticky": "nsew", "children": [
                    (indicator_elem, {"side": "left", "sticky": "nsew"}),
                    ("Treeitem.image", {"side": "left", "sticky": "nsew"}),
                    ("Treeitem.focus", {"side": "left", "sticky": "nsew", "children": [
                        ("Treeitem.text", {"side": "left", "sticky": "nsew"}),
                    ]}),
                ]}),
            ])
        except Exception:
            pass  # layout may already exist on re-open

        _bg = BG_LIST
        _fg = TEXT_MAIN
        style.configure("ModFiles.Treeview",
            background=_bg, foreground=_fg,
            fieldbackground=_bg, borderwidth=0,
            rowheight=scaled(22), font=("Cantarell", _theme.FS10),
            focuscolor=_bg,
        )
        style.map("ModFiles.Treeview",
            background=[("selected", _bg), ("focus", _bg)],
            foreground=[("selected", ACCENT)],
        )
        style.configure("ModFiles.Treeview.Heading",
            background=_bg, foreground=_fg,
            font=("Cantarell", _theme.FS10, "bold"), relief="flat",
        )

        self._mf_tree = ttk.Treeview(
            tab,
            columns=("toplevel", "check"),
            style="ModFiles.Treeview",
            selectmode="browse",
            show="tree headings",
        )
        self._mf_tree.heading("#0", text="File name", anchor="w")
        self._mf_tree.heading("toplevel", text="Top Level", anchor="center")
        self._mf_tree.heading("check", text="Disable", anchor="center")
        self._mf_tree.column("#0", stretch=True, minwidth=scaled(150))
        self._mf_tree.column("toplevel", width=scaled(70), minwidth=scaled(70), stretch=False, anchor="center")
        self._mf_tree.column("check", width=scaled(60), minwidth=scaled(60), stretch=False, anchor="center")

        _sb_bg     = SCROLL_BG
        _sb_trough = SCROLL_TROUGH
        _sb_active = SCROLL_ACTIVE
        vsb = tk.Scrollbar(
            tab, orient="vertical", command=self._mf_tree.yview,
            bg=_sb_bg, troughcolor=_sb_trough, activebackground=_sb_active,
            highlightthickness=0, bd=0,
        )
        self._mf_tree.configure(yscrollcommand=vsb.set)
        self._mf_tree.grid(row=1, column=0, sticky="nsew")
        vsb.grid(row=1, column=1, sticky="ns")

        if not LEGACY_WHEEL_REDUNDANT:
            self._mf_tree.bind("<Button-4>", lambda e: self._mf_tree.yview_scroll(-3, "units"))
            self._mf_tree.bind("<Button-5>", lambda e: self._mf_tree.yview_scroll(3, "units"))
        self._mf_tree.bind("<Button-1>", self._on_mf_click)
        self._mf_tree.bind("<space>", self._on_mf_space)
        self._mf_tree.bind("<Button-3>", self._on_mf_right_click)

        self._mf_checked: dict[str, bool] = {}   # iid → checked state
        self._mf_iid_to_key: dict[str, str | None] = {}  # iid → rel_key (None for folders)
        self._mf_iid_to_relstr: dict[str, str] = {}  # iid → rel_str (original-case, leaf nodes only)
        self._mf_folder_iids: set[str] = set()
        self._mf_iid_to_path: dict[str, str] = {}   # iid → canonical rel path (folder or file)
        self._mf_path_to_iid: dict[str, str] = {}   # canonical lowercase rel path → iid
        self._mf_top_level_iids: set[str] = set()   # iids eligible for the Top Level checkbox
        self._mf_stripped_paths: set[str] = set()   # lowercased strip-prefix entries for this mod (from profile_state)
        self._mf_synthetic_iids: set[str] = set()   # iids for synthetic strip placeholders

        # Footer with action buttons (Pack BSA, …). Row 2 stays a fixed-height
        # strip below the tree (row 1 carries the weight).
        tab.grid_rowconfigure(2, weight=0)
        footer = tk.Frame(tab, bg=BG_HEADER, height=scaled(32), highlightthickness=0)
        footer.grid(row=2, column=0, columnspan=2, sticky="ew")
        footer.grid_propagate(False)

        # Pack on the left (green = constructive), then Unpack to its
        # right (red = destructive — it removes archives from the mod).
        self._mf_pack_bsa_btn = ctk.CTkButton(
            footer, text="Pack BSA", width=100, height=24,
            fg_color=BTN_SUCCESS, hover_color=BTN_SUCCESS_HOV, text_color="white",
            font=(_theme.FONT_FAMILY, _theme.FS10), corner_radius=4,
            command=self._on_pack_bsa_click,
            state="disabled",
        )
        self._mf_pack_bsa_btn.pack(side="left", padx=(8, 4), pady=4)

        self._mf_unpack_bsa_btn = ctk.CTkButton(
            footer, text="Unpack BSA", width=100, height=24,
            fg_color=RED_BTN, hover_color=RED_HOV, text_color="white",
            font=(_theme.FONT_FAMILY, _theme.FS10), corner_radius=4,
            command=self._on_unpack_bsa_click,
            state="disabled",
        )
        self._mf_unpack_bsa_btn.pack(side="left", padx=(0, 4), pady=4)

        # Track the open overlay so we can close it from anywhere.
        self._bsa_unpack_overlay = None

    def _mf_check_symbol(self, iid: str) -> str:
        if iid in self._mf_folder_iids:
            children = self._mf_all_leaf_iids(iid)
            if not children:
                return self._MF_CHECK
            all_checked = all(self._mf_checked.get(c, True) for c in children)
            none_checked = not any(self._mf_checked.get(c, True) for c in children)
            if all_checked:
                return self._MF_CHECK
            if none_checked:
                return self._MF_UNCHECK
            return self._MF_PARTIAL
        return self._MF_CHECK if self._mf_checked.get(iid, True) else self._MF_UNCHECK

    def _mf_all_leaf_iids(self, iid: str) -> list[str]:
        result = []
        for child in self._mf_tree.get_children(iid):
            if child in self._mf_folder_iids:
                result.extend(self._mf_all_leaf_iids(child))
            else:
                result.append(child)
        return result

    def _mf_refresh_ancestors(self, iid: str):
        parent = self._mf_tree.parent(iid)
        while parent:
            sym = self._mf_check_symbol(parent)
            self._mf_tree.set(parent, "check", sym)
            # Grey the folder only if ALL of its leaves are disabled.
            leaves = self._mf_all_leaf_iids(parent)
            all_off = bool(leaves) and not any(
                self._mf_checked.get(l, True) for l in leaves
            )
            self._mf_apply_disabled_tag(parent, all_off)
            parent = self._mf_tree.parent(parent)

    def _on_mf_click(self, event):
        if getattr(self, "_mf_separator_view", False):
            return
        iid = self._mf_tree.identify_row(event.y)
        if not iid:
            return
        col = self._mf_tree.identify_column(event.x)
        if col == "#1":
            self._mf_toggle_top_level(iid)
            return
        if col == "#2":
            self._mf_toggle(iid)
            return

    def _on_mf_space(self, event):
        if getattr(self, "_mf_separator_view", False):
            return
        sel = self._mf_tree.selection()
        if sel:
            self._mf_toggle(sel[0])

    def _mf_apply_disabled_tag(self, iid: str, disabled: bool):
        """Add/remove the greyed ``mf_disabled`` tag based on disable state,
        preserving any other tags already on the row."""
        try:
            current = list(self._mf_tree.item(iid, "tags") or ())
        except Exception:
            return
        has = "mf_disabled" in current
        if disabled and not has:
            current.append("mf_disabled")
            self._mf_tree.item(iid, tags=tuple(current))
        elif not disabled and has:
            current.remove("mf_disabled")
            self._mf_tree.item(iid, tags=tuple(current))

    def _mf_set_subtree(self, iid: str, new_state: bool):
        """Recursively set all leaves and sub-folder symbols under iid."""
        for child in self._mf_tree.get_children(iid):
            if child in self._mf_folder_iids:
                self._mf_set_subtree(child, new_state)
                self._mf_tree.set(child, "check", self._mf_check_symbol(child))
                self._mf_apply_disabled_tag(child, not new_state)
            else:
                self._mf_checked[child] = new_state
                self._mf_tree.set(child, "check", self._MF_CHECK if new_state else self._MF_UNCHECK)
                self._mf_apply_disabled_tag(child, not new_state)

    def _mf_toggle(self, iid: str):
        if iid in self._mf_folder_iids:
            leaves = self._mf_all_leaf_iids(iid)
            all_checked = all(self._mf_checked.get(c, True) for c in leaves)
            new_state = not all_checked
            self._mf_set_subtree(iid, new_state)
            self._mf_tree.set(iid, "check", self._mf_check_symbol(iid))
            self._mf_apply_disabled_tag(iid, not new_state)
            self._mf_refresh_ancestors(iid)
        else:
            current = self._mf_checked.get(iid, True)
            self._mf_checked[iid] = not current
            self._mf_tree.set(iid, "check", self._MF_CHECK if not current else self._MF_UNCHECK)
            self._mf_apply_disabled_tag(iid, current)  # new state = not current → disabled when current was True
            self._mf_refresh_ancestors(iid)
        self._mf_save_and_rebuild()

    def _mf_save_and_rebuild(self):
        """Persist current exclusions for the displayed mod and trigger filemap rebuild."""
        if self._mod_files_mod_name is None or self._mod_files_profile_dir is None:
            return
        mod_name = self._mod_files_mod_name
        profile_dir = self._mod_files_profile_dir
        excluded_keys = [
            self._mf_iid_to_key[iid]
            for iid, checked in self._mf_checked.items()
            if not checked and self._mf_iid_to_key.get(iid) is not None
        ]
        all_excluded = read_excluded_mod_files(profile_dir, None)
        if excluded_keys:
            all_excluded[mod_name] = sorted(excluded_keys)
        else:
            all_excluded.pop(mod_name, None)
        write_excluded_mod_files(profile_dir, all_excluded)
        self._mod_files_excluded = {k: set(v) for k, v in all_excluded.items()}
        self._log(
            f"Mod Files: saved {len(excluded_keys)} exclusion(s) for '{mod_name}' "
            f"(profile_state excluded_mod_files)"
        )
        if self._mod_files_on_change is not None:
            self._mod_files_on_change()

    # ------------------------------------------------------------------
    # Top-level selection (Mod Files tab)
    # ------------------------------------------------------------------
    #
    # The Top Level checkbox appears on every row (folders and files).
    # A row is "checked" when, under the current strip list, its entire
    # parent path is stripped away — i.e. the row itself would deploy as
    # top-level. Checking a nested row adds all of its ancestor path
    # segments to the strip list, which visually unchecks + greys those
    # ancestors. Unchecking a currently-top-level row re-introduces its
    # parent path by removing it from the strip list. Synthetic greyed
    # rows are added for strip entries that aren't otherwise visible so
    # the user can re-check (un-strip) them.

    def _mf_parent_path(self, path: str) -> str:
        """Return the parent folder path of ``path`` (or '')."""
        p = path.replace("\\", "/").rstrip("/")
        if "/" not in p:
            return ""
        return p.rsplit("/", 1)[0]

    def _mf_ancestor_paths(self, path: str) -> list[str]:
        """Return ancestor folder paths of ``path`` from root to parent."""
        p = path.replace("\\", "/").rstrip("/")
        if "/" not in p:
            return []
        segs = p.split("/")[:-1]
        out: list[str] = []
        cur = ""
        for s in segs:
            cur = f"{cur}/{s}" if cur else s
            out.append(cur)
        return out

    def _mf_is_top_level(self, path: str) -> bool:
        """Return True if ``path`` currently deploys as top-level given the
        strip list (i.e. its parent path is fully covered by strip entries)."""
        parent = self._mf_parent_path(path)
        if not parent:
            return True
        return parent.lower() in self._mf_stripped_paths

    def _mf_insert_stripped_placeholders(self):
        """Insert synthetic top rows for strip entries that aren't already
        present in the tree. These appear greyed + unchecked so the user
        can re-check to un-strip."""
        existing_paths = {p.lower() for p in self._mf_iid_to_path.values() if p}
        for entry_l in sorted(self._mf_stripped_paths):
            if not entry_l or entry_l in existing_paths:
                continue
            # Find the original-case form from the strip map.
            if self._mod_files_profile_dir is None:
                display = entry_l
            else:
                strip_map = read_mod_strip_prefixes(self._mod_files_profile_dir, None)
                display = entry_l
                for e in strip_map.get(self._mod_files_mod_name or "", []):
                    if e.lower() == entry_l:
                        display = e
                        break
            iid = self._mf_tree.insert(
                "", 0,
                text=display,
                values=("", self._MF_UNCHECK),
                tags=("mf_stripped",),
            )
            self._mf_iid_to_key[iid] = None
            self._mf_iid_to_path[iid] = display
            self._mf_path_to_iid[display.lower()] = iid
            self._mf_top_level_iids.add(iid)
            self._mf_synthetic_iids.add(iid)

    def _mf_prune_stale_placeholders(self):
        """Remove synthetic strip-placeholder rows whose path is no longer
        in the strip list, and add new synthetic rows for any strip entries
        that no longer map to a real tree row."""
        stripped = self._mf_stripped_paths
        for iid in list(self._mf_synthetic_iids):
            path = self._mf_iid_to_path.get(iid, "")
            path_l = path.lower()
            if path_l not in stripped:
                try:
                    self._mf_tree.delete(iid)
                except Exception:
                    pass
                self._mf_synthetic_iids.discard(iid)
                self._mf_top_level_iids.discard(iid)
                self._mf_iid_to_path.pop(iid, None)
                self._mf_iid_to_key.pop(iid, None)
                self._mf_path_to_iid.pop(path_l, None)
        self._mf_insert_stripped_placeholders()
        self._mf_refresh_top_level_column()

    def _mf_refresh_leaf_keys(self):
        """After the strip list changes, re-derive each leaf's post-strip
        rel_key from the raw rel_str so the Disable column writes the right
        key to `excluded_mod_files`."""
        for iid, rel_str in self._mf_iid_to_relstr.items():
            if not rel_str:
                continue
            raw_key = rel_str.replace("\\", "/").lower()
            post_key = raw_key
            for s in sorted(self._mf_stripped_paths, key=len, reverse=True):
                sl = s.lower()
                if post_key == sl or post_key.startswith(sl + "/"):
                    post_key = post_key[len(sl):].lstrip("/")
                    break
            self._mf_iid_to_key[iid] = post_key

    def _mf_refresh_top_level_column(self):
        """Update the Top Level column glyphs + greyed styling on every row.

        A row's checkbox is:
          - Checked when it currently deploys as top-level (its parent path
            is covered by the strip list or it has no parent).
          - Unchecked + greyed when the row's own path is in the strip list
            (i.e. this row has been stripped to promote a descendant).
          - Unchecked (not greyed) for deeper rows that could be promoted.
        """
        self._mf_refresh_leaf_keys()
        stripped = self._mf_stripped_paths
        tree_set = self._mf_tree.set
        TL_SEL = self._MF_TL_SEL
        TL_UNSEL = self._MF_TL_UNSEL
        for iid, path in self._mf_iid_to_path.items():
            if not path:
                tree_set(iid, "toplevel", "")
                continue
            # Inline _mf_is_top_level: derive parent path from a normalized
            # lowercased copy, but keep the original-case lower() for the
            # is_stripped test to match historical semantics.
            path_l = path.lower()
            is_stripped = path_l in stripped
            norm_l = path_l.replace("\\", "/").rstrip("/")
            slash = norm_l.rfind("/")
            is_top = slash < 0 or norm_l[:slash] in stripped
            tree_set(iid, "toplevel", TL_UNSEL if is_stripped or not is_top else TL_SEL)
            self._apply_stripped_tag(iid, is_stripped)

    def _apply_stripped_tag(self, iid: str, stripped: bool):
        current = list(self._mf_tree.item(iid, "tags") or ())
        has = "mf_stripped" in current
        if stripped and not has:
            current.append("mf_stripped")
            self._mf_tree.item(iid, tags=tuple(current))
        elif not stripped and has:
            current.remove("mf_stripped")
            self._mf_tree.item(iid, tags=tuple(current))

    def _mf_toggle_top_level(self, iid: str):
        """Promote/demote the row's path as top-level.

        - Checking a not-top-level row: add every ancestor path segment to
          the strip list so this row becomes top-level. Previously
          top-level ancestors become unchecked + greyed.
        - Unchecking a currently top-level row: remove its parent path
          from the strip list (so the parent reappears as top-level).
          Root-level rows (no parent) have no effect.
        - Unchecking a stripped row (greyed): remove it from the strip
          list so it returns to being top-level.
        """
        if self._mod_files_mod_name is None or self._mod_files_profile_dir is None:
            return
        path = self._mf_iid_to_path.get(iid)
        if not path:
            return

        path_l = path.lower()

        def _unstrip_subtree(root_l: str):
            """Remove ``root_l`` and every strip entry beneath it."""
            prefix = root_l + "/"
            for s in list(self._mf_stripped_paths):
                if s == root_l or s.startswith(prefix):
                    self._mf_stripped_paths.discard(s)

        if path_l in self._mf_stripped_paths:
            # Un-strip this path (and any stripped descendants so that no
            # deeper row remains "promoted" past the reclaimed ancestor).
            _unstrip_subtree(path_l)
        elif self._mf_is_top_level(path):
            # Currently top-level → demote by unstripping its parent and
            # anything further down that chain.
            parent = self._mf_parent_path(path)
            if parent:
                _unstrip_subtree(parent.lower())
            else:
                # No parent to demote — ignore.
                return
        else:
            # Promote this row: strip every ancestor segment up to it.
            for anc in self._mf_ancestor_paths(path):
                self._mf_stripped_paths.add(anc.lower())

        # Persist the full strip list (preserve original-case forms where known).
        mod_name = self._mod_files_mod_name
        profile_dir = self._mod_files_profile_dir
        path_lower_to_orig: dict[str, str] = {}
        for p in self._mf_iid_to_path.values():
            if p:
                path_lower_to_orig.setdefault(p.lower(), p)
                # Record ancestor path chunks too so we can preserve case on strips.
                for anc in self._mf_ancestor_paths(p):
                    path_lower_to_orig.setdefault(anc.lower(), anc)
        strip_map = read_mod_strip_prefixes(profile_dir, None)
        existing = strip_map.get(mod_name, [])
        for e in existing:
            if e:
                path_lower_to_orig.setdefault(e.lower(), e)
        merged = sorted(
            {path_lower_to_orig.get(s, s) for s in self._mf_stripped_paths if s}
        )
        if merged:
            strip_map[mod_name] = merged
        else:
            strip_map.pop(mod_name, None)
        write_mod_strip_prefixes(profile_dir, strip_map)

        # Refresh modlist panel's cache so the next filemap rebuild sees the
        # updated prefixes, and force a full re-scan of the mod index since
        # strip prefixes are applied during the scan, not at filemap merge.
        app = self.winfo_toplevel()
        mod_panel = getattr(app, "_mod_panel", None)
        if mod_panel is not None:
            # Invalidate the cached profile_state copy so _load_mod_strip_prefixes
            # re-reads from disk instead of returning the stale cached dict.
            try:
                cache = getattr(mod_panel, "_ModListPanel__profile_state", None)
                if isinstance(cache, dict):
                    cache.pop("mod_strip_prefixes", None)
            except Exception:
                pass
            if hasattr(mod_panel, "_load_mod_strip_prefixes"):
                try:
                    mod_panel._load_mod_strip_prefixes()
                except Exception:
                    pass
            try:
                mod_panel._filemap_rescan_index = True
            except Exception:
                pass

        self._mf_refresh_top_level_column()
        self._log(
            f"Mod Files: strip prefixes for '{mod_name}' = "
            f"{merged if merged else '(none)'}"
        )
        if self._mod_files_on_change is not None:
            self._mod_files_on_change()
        # Also refresh any synthetic rows for strip entries that are no
        # longer represented in the tree (e.g. when an ancestor was
        # unstripped, remove its stale synthetic placeholder).
        self._mf_prune_stale_placeholders()

    def _mf_refresh_current_view(self):
        """Re-render the Mod Files tab using whichever view is active —
        either the single-mod path or the separator path."""
        if getattr(self, "_mf_separator_view", False):
            self.show_mod_files_for_separator(
                getattr(self, "_mf_separator_name", "") or "",
                getattr(self, "_mf_separator_mods", []) or [],
            )
        else:
            self.show_mod_files(self._mod_files_mod_name)

    def show_mod_files(self, mod_name: str | None):
        """Populate the Mod Files tab for the given mod name."""
        # Switching back from a separator view: drop the read-only flag so
        # checkbox clicks resume working for the regular single-mod tree.
        self._mf_separator_view = False
        self._mf_separator_name = None
        self._mf_separator_mods = []
        # Capture expand state (by path) + scroll position if we're rebuilding
        # the same mod, so the tree doesn't collapse / jump on every edit.
        prev_expanded: set[str] = set()
        prev_scroll: tuple[float, float] | None = None
        if (mod_name is not None and mod_name == self._mod_files_mod_name):
            for iid, path in self._mf_iid_to_path.items():
                try:
                    if self._mf_tree.item(iid, "open") and path:
                        prev_expanded.add(path.lower())
                except Exception:
                    pass
            try:
                prev_scroll = self._mf_tree.yview()
            except Exception:
                prev_scroll = None

        self._mod_files_mod_name = mod_name
        self._update_pack_bsa_button_state()
        # Clear tree
        self._mf_tree.delete(*self._mf_tree.get_children())
        self._mf_checked.clear()
        self._mf_iid_to_key.clear()
        self._mf_iid_to_relstr.clear()
        self._mf_folder_iids.clear()
        self._mf_iid_to_path.clear()
        self._mf_path_to_iid.clear()
        self._mf_top_level_iids.clear()
        self._mf_stripped_paths.clear()
        self._mf_synthetic_iids.clear()
        self._mf_prev_expanded_paths = prev_expanded
        self._mf_prev_scroll = prev_scroll

        if mod_name is None:
            self._mod_files_label.configure(text="(no mod selected)")
            return

        self._mod_files_label.configure(text=mod_name)
        self._mf_tree_expanded = False
        self._mf_expand_btn.configure(text="⊞ Expand All")

        # Load current exclusions for this mod
        excluded_keys: set[str] = set()
        if self._mod_files_profile_dir is not None:
            excluded_keys = self._mod_files_excluded.get(mod_name, set())

        # Load current strip-prefix selection for this mod.
        if self._mod_files_profile_dir is not None:
            strip_map = read_mod_strip_prefixes(self._mod_files_profile_dir, None)
            for entry in strip_map.get(mod_name, []):
                if entry:
                    self._mf_stripped_paths.add(entry.lower())

        # Load conflict data from the (post-strip) index — needed to tag rows.
        full_index = None
        if self._mod_files_index_path is not None:
            from Utils.filemap import read_mod_index
            full_index = read_mod_index(self._mod_files_index_path)

        # Load the raw file listing by scanning the mod folder directly so
        # the tree shows the full on-disk structure regardless of currently-
        # saved strip prefixes. This lets the user tick nested folders as
        # the new top level without first needing a full rescan.
        files: dict[str, str] = {}   # rel_key → rel_str (raw, no strip applied)
        mod_dir: Path | None = None
        if self._game is not None:
            if mod_name == _OVERWRITE_NAME and hasattr(self._game, "get_effective_overwrite_path"):
                try:
                    mod_dir = Path(self._game.get_effective_overwrite_path())
                except Exception:
                    mod_dir = None
            elif hasattr(self._game, "get_effective_mod_staging_path"):
                try:
                    mod_dir = Path(self._game.get_effective_mod_staging_path()) / mod_name
                except Exception:
                    mod_dir = None
        if mod_dir is not None and mod_dir.is_dir():
            from Utils.filemap import _scan_dir
            _name, _normal, _root, _invalid = _scan_dir(
                mod_name, str(mod_dir),
            )
            files.update(_normal)
            files.update(_root)

        if not files:
            self._mf_tree.insert("", "end", text="  (no files found — try refreshing)", tags=("dim",))
            self._mf_tree.tag_configure("dim", foreground=TEXT_DIM)
            return

        # Build conflict lookup sets from filemap.txt and full mod index.
        contested_keys, filemap_winner = self._get_conflict_cache(full_index)

        def _rel_key_after_strip(raw_rel_key: str) -> str:
            """Apply currently-saved strip prefixes to a raw rel_key so we
            can look it up in the (post-strip) conflict/filemap data."""
            k = raw_rel_key
            # longest-match first, same as _scan_dir
            for s in sorted(self._mf_stripped_paths, key=len, reverse=True):
                sl = s.lower()
                if k == sl or k.startswith(sl + "/"):
                    k = k[len(sl):].lstrip("/")
                    break
            # also handle the legacy strip_prefixes (first-segment) — not used
            # by the Top Level column, so we skip it here.
            return k

        # Configure conflict highlight tags
        self._mf_tree.tag_configure("dim", foreground=TEXT_DIM)
        self._mf_tree.tag_configure("conflict_win",  foreground=_theme.conflict_higher)
        self._mf_tree.tag_configure("conflict_lose", foreground=_theme.conflict_lower)

        def _conflict_tag(rel_key: str) -> str | None:
            # Conflict data is keyed by the post-strip rel_key.
            key = _rel_key_after_strip(rel_key)
            if key not in contested_keys:
                return None
            winner = filemap_winner.get(key.lower())
            if winner is None:
                return None
            return "conflict_win" if winner == mod_name else "conflict_lose"

        only_conflicts = bool(
            self._mf_only_conflicts_var and self._mf_only_conflicts_var.get()
        )

        # Build tree structure
        tree_dict: dict = {}
        for rel_key, rel_str in sorted(files.items()):
            if only_conflicts and _conflict_tag(rel_key) is None:
                continue
            parts = rel_str.replace("\\", "/").split("/")
            node = tree_dict
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node.setdefault("__files__", []).append((parts[-1], rel_key, rel_str))

        if only_conflicts and not tree_dict:
            self._mf_tree.insert("", "end", text="  (no conflicts)", tags=("dim",))
            return

        # Configure the "stripped" tag used to grey out unchecked top-level rows.
        self._mf_tree.tag_configure("mf_stripped", foreground=TEXT_DIM)
        # Configure the "disabled" tag used to grey out rows excluded via the Disable column.
        self._mf_tree.tag_configure("mf_disabled", foreground=TEXT_DIM)

        def insert_node(parent_id, name, subtree, parent_path, depth=0):
            folder_path = f"{parent_path}/{name}" if parent_path else name
            iid = self._mf_tree.insert(
                parent_id, "end",
                text=name,
                values=("", self._MF_CHECK),
                open=(depth == 0),
            )
            self._mf_folder_iids.add(iid)
            self._mf_iid_to_key[iid] = None
            self._mf_iid_to_path[iid] = folder_path
            self._mf_path_to_iid[folder_path.lower()] = iid
            self._mf_top_level_iids.add(iid)
            for child in sorted(k for k in subtree if k != "__files__"):
                insert_node(iid, child, subtree[child], folder_path, depth + 1)
            for fname, rel_key, rel_str in sorted(subtree.get("__files__", [])):
                post_key = _rel_key_after_strip(rel_key)
                checked = post_key not in excluded_keys
                tag = _conflict_tag(rel_key)
                tags: tuple[str, ...] = (tag,) if tag else ()
                if not checked:
                    tags = tags + ("mf_disabled",)
                leaf_iid = self._mf_tree.insert(
                    iid, "end",
                    text=fname,
                    values=("", self._MF_CHECK if checked else self._MF_UNCHECK),
                    tags=tags,
                )
                self._mf_checked[leaf_iid] = checked
                self._mf_iid_to_key[leaf_iid] = post_key
                self._mf_iid_to_relstr[leaf_iid] = rel_str
                file_path = f"{folder_path}/{fname}" if folder_path else fname
                self._mf_iid_to_path[leaf_iid] = file_path
                self._mf_path_to_iid[file_path.lower()] = leaf_iid
                self._mf_top_level_iids.add(leaf_iid)
            # Set correct folder symbol now that all children exist
            self._mf_tree.set(iid, "check", self._mf_check_symbol(iid))

        for top in sorted(k for k in tree_dict if k != "__files__"):
            insert_node("", top, tree_dict[top], "")
        # Root-level files (unlikely but handle anyway)
        for fname, rel_key, rel_str in sorted(tree_dict.get("__files__", [])):
            post_key = _rel_key_after_strip(rel_key)
            checked = post_key not in excluded_keys
            tag = _conflict_tag(rel_key)
            tags: tuple[str, ...] = (tag,) if tag else ()
            if not checked:
                tags = tags + ("mf_disabled",)
            leaf_iid = self._mf_tree.insert(
                "", "end", text=fname,
                values=("", self._MF_CHECK if checked else self._MF_UNCHECK),
                tags=tags,
            )
            self._mf_checked[leaf_iid] = checked
            self._mf_iid_to_key[leaf_iid] = post_key
            self._mf_iid_to_relstr[leaf_iid] = rel_str
            self._mf_iid_to_path[leaf_iid] = fname
            self._mf_path_to_iid[fname.lower()] = leaf_iid
            self._mf_top_level_iids.add(leaf_iid)

        # Render synthetic greyed rows for strip entries that don't appear as
        # depth-0 rows in the current tree, so the user can un-strip them.
        self._mf_insert_stripped_placeholders()

        # Apply Top Level column visuals.
        self._mf_refresh_top_level_column()

        # Grey any folder whose leaves are all disabled.
        for fid in self._mf_folder_iids:
            leaves = self._mf_all_leaf_iids(fid)
            all_off = bool(leaves) and not any(
                self._mf_checked.get(l, True) for l in leaves
            )
            if all_off:
                self._mf_apply_disabled_tag(fid, True)

        # Restore expand state + scroll from the previous render of this mod.
        prev = getattr(self, "_mf_prev_expanded_paths", None)
        if prev:
            for iid, path in self._mf_iid_to_path.items():
                if path and path.lower() in prev:
                    try:
                        self._mf_tree.item(iid, open=True)
                    except Exception:
                        pass
        prev_scroll = getattr(self, "_mf_prev_scroll", None)
        if prev_scroll:
            try:
                self._mf_tree.yview_moveto(prev_scroll[0])
            except Exception:
                pass

    def show_mod_files_for_separator(
        self, separator_name: str, mod_names: list[str],
    ):
        """Populate the Mod Files tab with one top-level node per mod under
        the given separator. Read-only — clicking the checkbox columns is
        suppressed in this mode (see ``_mf_separator_view``)."""
        # Capture expand state when re-rendering the same separator so the
        # tree doesn't collapse on toggle / refresh.
        prev_expanded: set[str] = set()
        prev_scroll: tuple[float, float] | None = None
        if (getattr(self, "_mf_separator_view", False)
                and getattr(self, "_mf_separator_name", None) == separator_name):
            for iid, path in self._mf_iid_to_path.items():
                try:
                    if self._mf_tree.item(iid, "open") and path:
                        prev_expanded.add(path.lower())
                except Exception:
                    pass
            try:
                prev_scroll = self._mf_tree.yview()
            except Exception:
                prev_scroll = None

        self._mf_separator_view = True
        self._mf_separator_name = separator_name
        self._mf_separator_mods = list(mod_names)
        # Disable the per-mod state used by the single-mod editing path so
        # any stray callbacks (e.g. _mf_save_and_rebuild) become no-ops.
        self._mod_files_mod_name = None
        self._update_pack_bsa_button_state()
        self._mf_tree.delete(*self._mf_tree.get_children())
        self._mf_checked.clear()
        self._mf_iid_to_key.clear()
        self._mf_iid_to_relstr.clear()
        self._mf_folder_iids.clear()
        self._mf_iid_to_path.clear()
        self._mf_path_to_iid.clear()
        self._mf_top_level_iids.clear()
        self._mf_stripped_paths.clear()
        self._mf_synthetic_iids.clear()

        if not mod_names:
            self._mod_files_label.configure(
                text=f"{separator_name} — (no mods in this separator)"
            )
            return

        self._mod_files_label.configure(
            text=f"{separator_name} — {len(mod_names)} mod(s) (read-only)"
        )
        self._mf_tree_expanded = False
        self._mf_expand_btn.configure(text="⊞ Expand All")

        # Conflict cache (post-strip rel_keys → winner). Reuse the same data
        # as the single-mod view so colouring stays consistent.
        full_index = None
        if self._mod_files_index_path is not None:
            from Utils.filemap import read_mod_index
            full_index = read_mod_index(self._mod_files_index_path)
        contested_keys, filemap_winner = self._get_conflict_cache(full_index)

        # Per-mod strip-prefix lookup so conflict tagging keys match what
        # the filemap actually deploys.
        strip_map: dict[str, list[str]] = {}
        if self._mod_files_profile_dir is not None:
            try:
                strip_map = read_mod_strip_prefixes(
                    self._mod_files_profile_dir, None,
                )
            except Exception:
                strip_map = {}

        self._mf_tree.tag_configure("dim", foreground=TEXT_DIM)
        self._mf_tree.tag_configure("conflict_win",  foreground=_theme.conflict_higher)
        self._mf_tree.tag_configure("conflict_lose", foreground=_theme.conflict_lower)
        self._mf_tree.tag_configure("mf_stripped", foreground=TEXT_DIM)
        self._mf_tree.tag_configure("mf_disabled", foreground=TEXT_DIM)

        only_conflicts = bool(
            self._mf_only_conflicts_var and self._mf_only_conflicts_var.get()
        )

        from Utils.filemap import _scan_dir
        staging_dir: Path | None = None
        if self._game is not None and hasattr(self._game, "get_effective_mod_staging_path"):
            try:
                staging_dir = Path(self._game.get_effective_mod_staging_path())
            except Exception:
                staging_dir = None
        overwrite_dir: Path | None = None
        if self._game is not None and hasattr(self._game, "get_effective_overwrite_path"):
            try:
                overwrite_dir = Path(self._game.get_effective_overwrite_path())
            except Exception:
                overwrite_dir = None

        rendered_any = False
        for mod_name in mod_names:
            stripped_for_mod = {
                e.lower() for e in strip_map.get(mod_name, []) if e
            }

            if mod_name == _OVERWRITE_NAME:
                mod_dir = overwrite_dir
            elif staging_dir is not None:
                mod_dir = staging_dir / mod_name
            else:
                mod_dir = None

            files: dict[str, str] = {}
            if mod_dir is not None and mod_dir.is_dir():
                _name, _normal, _root, _invalid = _scan_dir(
                    mod_name, str(mod_dir),
                )
                files.update(_normal)
                files.update(_root)

            def _post_strip(raw_rel_key: str, _stripped=stripped_for_mod) -> str:
                k = raw_rel_key
                for s in sorted(_stripped, key=len, reverse=True):
                    if k == s or k.startswith(s + "/"):
                        k = k[len(s):].lstrip("/")
                        break
                return k

            def _conflict_tag(rel_key: str, _owner=mod_name,
                              _post=_post_strip) -> str | None:
                key = _post(rel_key)
                if key not in contested_keys:
                    return None
                winner = filemap_winner.get(key.lower())
                if winner is None:
                    return None
                return "conflict_win" if winner == _owner else "conflict_lose"

            tree_dict: dict = {}
            for rel_key, rel_str in sorted(files.items()):
                if only_conflicts and _conflict_tag(rel_key) is None:
                    continue
                parts = rel_str.replace("\\", "/").split("/")
                node = tree_dict
                for part in parts[:-1]:
                    node = node.setdefault(part, {})
                node.setdefault("__files__", []).append((parts[-1], rel_key, rel_str))

            if only_conflicts and not tree_dict:
                continue
            if not files:
                continue

            rendered_any = True
            mod_iid = self._mf_tree.insert(
                "", "end",
                text=mod_name,
                values=("", ""),
                open=False,
                tags=("dim",),
            )
            self._mf_folder_iids.add(mod_iid)
            self._mf_iid_to_path[mod_iid] = mod_name

            def _insert_node(parent_id, name, subtree, parent_path, depth):
                folder_path = f"{parent_path}/{name}" if parent_path else name
                iid = self._mf_tree.insert(
                    parent_id, "end",
                    text=name,
                    values=("", ""),
                    open=False,
                )
                self._mf_folder_iids.add(iid)
                self._mf_iid_to_path[iid] = folder_path
                for child in sorted(k for k in subtree if k != "__files__"):
                    _insert_node(iid, child, subtree[child], folder_path, depth + 1)
                for fname, rel_key, rel_str in sorted(subtree.get("__files__", [])):
                    tag = _conflict_tag(rel_key)
                    tags: tuple[str, ...] = (tag,) if tag else ()
                    leaf_iid = self._mf_tree.insert(
                        iid, "end",
                        text=fname,
                        values=("", ""),
                        tags=tags,
                    )
                    self._mf_iid_to_relstr[leaf_iid] = rel_str
                    file_path = f"{folder_path}/{fname}" if folder_path else fname
                    self._mf_iid_to_path[leaf_iid] = file_path

            mod_path_prefix = mod_name
            for top in sorted(k for k in tree_dict if k != "__files__"):
                _insert_node(mod_iid, top, tree_dict[top], mod_path_prefix, 1)
            for fname, rel_key, rel_str in sorted(tree_dict.get("__files__", [])):
                tag = _conflict_tag(rel_key)
                tags: tuple[str, ...] = (tag,) if tag else ()
                leaf_iid = self._mf_tree.insert(
                    mod_iid, "end",
                    text=fname,
                    values=("", ""),
                    tags=tags,
                )
                self._mf_iid_to_relstr[leaf_iid] = rel_str
                self._mf_iid_to_path[leaf_iid] = f"{mod_path_prefix}/{fname}"

        if not rendered_any:
            placeholder = (
                "  (no conflicts in this separator)"
                if only_conflicts else
                "  (no files found in mods under this separator)"
            )
            self._mf_tree.insert("", "end", text=placeholder, tags=("dim",))
            return

        # Restore expand / scroll state from the previous separator render.
        if prev_expanded:
            for iid, path in self._mf_iid_to_path.items():
                if path and path.lower() in prev_expanded:
                    try:
                        self._mf_tree.item(iid, open=True)
                    except Exception:
                        pass
        if prev_scroll:
            try:
                self._mf_tree.yview_moveto(prev_scroll[0])
            except Exception:
                pass

    def _toggle_mf_tree_expand(self):
        """Expand all folders in the Mod Files tree, or collapse them if already expanded."""
        self._mf_tree_expanded = not self._mf_tree_expanded
        open_state = self._mf_tree_expanded

        def _set_all(item):
            children = self._mf_tree.get_children(item)
            if children:
                self._mf_tree.item(item, open=open_state)
                for child in children:
                    _set_all(child)

        for top in self._mf_tree.get_children(""):
            _set_all(top)

        self._mf_expand_btn.configure(
            text="⊟ Collapse All" if self._mf_tree_expanded else "⊞ Expand All"
        )

    def _on_mf_right_click(self, event):
        """Show context menu for Mod Files tree rows."""
        if getattr(self, "_mf_separator_view", False):
            return
        iid = self._mf_tree.identify_row(event.y)
        if not iid:
            return
        staging = self._get_staging_path()
        mod_name = self._mod_files_mod_name
        if staging is None or mod_name is None:
            return

        rel_str = self._mf_iid_to_relstr.get(iid)
        is_folder = iid in self._mf_folder_iids

        if rel_str:
            target = Path(staging) / mod_name / rel_str.replace("\\", "/")
            open_path = target.parent
        elif is_folder:
            # Reconstruct folder path from tree labels
            parts = []
            cur = iid
            while cur:
                parts.append(self._mf_tree.item(cur, "text"))
                cur = self._mf_tree.parent(cur)
            parts.reverse()
            open_path = Path(staging) / mod_name / Path(*parts)
        else:
            return

        self._show_simple_context_menu(self._mf_tree, event.x_root, event.y_root, [
            ("Open in File Browser", lambda p=open_path: self._open_folder_in_browser(p)),
        ])
