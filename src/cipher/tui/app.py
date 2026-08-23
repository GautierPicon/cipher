import threading
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    DirectoryTree,
    Footer,
    Header,
    ProgressBar,
    RichLog,
    Static,
)

from cipher.password import copy_to_clipboard, schedule_clipboard_clear
from cipher.service import (
    DestinationExistsError,
    decrypt_file,
    default_enc_dest,
    encrypt_path,
    verify_file,
)
from cipher.tui.modals import (
    ConfirmScreen,
    ConflictScreen,
    GeneratedPasswordScreen,
    PasswordModal,
)
from cipher.utils import sizeof_fmt


def _node_path(node) -> Path | None:
    data = node.data
    if data is None:
        return None
    return Path(data.path) if hasattr(data, "path") else Path(str(data))


class CipherTree(DirectoryTree):
    """DirectoryTree with dotfile filtering, file sizes and multi-selection."""

    BINDINGS: ClassVar = [
        Binding(
            "space",
            "toggle_select_cursor",
            "Select",
            key_display="space",
        ),
        Binding(
            "enter",
            "select_cursor",
            "Expand",
            key_display="enter",
        ),
    ]

    def __init__(self, path: Path, **kwargs) -> None:
        super().__init__(path, **kwargs)
        self.selected_paths: set[Path] = set()
        self.border_title = "Files"

    def action_toggle_select_cursor(self) -> None:
        self.app.action_toggle_select()

    def filter_paths(self, paths):
        return [p for p in paths if not p.name.startswith(".")]

    def render_label(self, node, base_style, style) -> Text:
        label = super().render_label(node, base_style, style)
        data = node.data
        if data is not None and not node._allow_expand:
            path = Path(data.path)
            try:
                label.append(f"  · {sizeof_fmt(path.stat().st_size)}", style="dim")
            except OSError:
                pass
        return label

    def toggle_selection(self, node) -> None:
        path = _node_path(node)
        if path is None:
            return
        if path in self.selected_paths:
            self.selected_paths.discard(path)
            self._set_label(node, str(node.label).removesuffix("  ✔"))
        else:
            self.selected_paths.add(path)
            self._set_label(node, str(node.label) + "  ✔")
        self._refresh_node(node)

    def clear_selection(self) -> None:
        for node in self.walk_nodes():
            label = str(node.label)
            if label.endswith("  ✔"):
                self._set_label(node, label.removesuffix("  ✔"))
                self._refresh_node(node)
        self.selected_paths.clear()

    def purge_missing(self) -> None:
        self.selected_paths = {p for p in self.selected_paths if p.exists()}

    def restore_markers(self) -> None:
        for node in self.walk_nodes():
            path = _node_path(node)
            if path is None:
                continue
            label = str(node.label).removesuffix("  ✔")
            if path in self.selected_paths:
                self._set_label(node, label + "  ✔")
            else:
                self._set_label(node, label)

    def walk_nodes(self):
        stack = [self.root]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(node.children)

    @staticmethod
    def _set_label(node, text: str) -> None:
        node.label = Text(text)


class CipherApp(App):
    TITLE = "cipher"
    SUB_TITLE = "AES-256-GCM file encryption"
    AUTO_FOCUS = "#tree"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS: ClassVar = [
        ("e", "encrypt", "Encrypt"),
        ("d", "decrypt", "Decrypt"),
        ("v", "verify", "Verify"),
        ("space", "toggle_select", "Select"),
        ("c", "clear_selection", "Clear selection"),
        ("x", "clear_activity", "Clear log"),
        ("k", "toggle_keys", "Keys"),
        ("q", "quit", "Quit"),
    ]

    CSS: ClassVar = """
    #main {
        height: 3fr;
    }
    #tree {
        width: 2fr;
        height: 100%;
        border: round $primary;
    }
    #sidebar {
        width: 1fr;
        height: 100%;
        border: round $primary;
        padding: 1 2;
        overflow-y: auto;
    }
    #progress {
        display: none;
        margin: 0 1;
    }
    #activity {
        height: 2fr;
        border: round $secondary;
    }
    #log {
        height: 1fr;
    }
    #log-buttons Button {
        min-width: 10;
        height: 1;
        border: none;
        background: transparent;
        color: $text-muted;
    }
    #log-buttons {
        height: 1;
        align-horizontal: right;
        margin-right: 2;
    }
    #status-bar {
        height: 1;
        background: $accent;
        color: $text;
        padding: 0 2;
    }
    """

    def __init__(self, start_path: Path | None = None) -> None:
        super().__init__()
        self.theme = "tokyo-night"
        self.start_path = start_path or Path.home()
        self._busy = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            yield CipherTree(self.start_path, id="tree")
            yield Static("", id="sidebar")
        yield ProgressBar(id="progress", show_eta=False)
        with Vertical(id="activity"):
            with Horizontal(id="log-buttons"):
                yield Button("Clear", variant="default", id="btn-clear-log")
            yield RichLog(id="log", markup=True, highlight=False)
        yield Static("", id="status-bar")
        yield Footer()

    @property
    def _tree(self) -> CipherTree:
        return self.query_one("#tree", CipherTree)

    def on_mount(self) -> None:
        self.query_one("#activity", Vertical).border_title = "Activity"
        self.query_one("#log", RichLog).write("[bold]Welcome to cipher[/bold]")
        self._update_sidebar()
        self._update_status()

    def action_clear_activity(self) -> None:
        log = self.query_one("#log", RichLog)
        log.clear()
        log.write("[bold]Welcome to cipher[/bold]")

    def action_toggle_keys(self) -> None:
        from textual.widgets import HelpPanel

        if self.screen.query(HelpPanel):
            self.action_hide_help_panel()
        else:
            self.action_show_help_panel()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-clear-log":
            self.action_clear_activity()



    @property
    def cursor_path(self) -> Path | None:
        node = self._tree.cursor_node
        return _node_path(node) if node is not None else None

    def _log(self, message: str) -> None:
        log = self.query_one("#log", RichLog)
        if self._thread_id == threading.get_ident():
            log.write(message)
        else:
            self.call_from_thread(log.write, message)

    def on_tree_node_highlighted(self, event) -> None:
        self._update_sidebar()

    def _update_sidebar(self) -> None:
        sidebar = self.query_one("#sidebar", Static)
        path = self.cursor_path
        if path is None:
            sidebar.update("")
            return
        selected = path in self._tree.selected_paths
        lines = [f"[b]{path.name}[/b]", ""]
        if path.is_dir():
            kind = "[b]Folder[/b]"
        elif path.suffix == ".enc":
            kind = "[green]Encrypted file[/green]"
        else:
            kind = "File"
        try:
            size = sizeof_fmt(path.stat().st_size) if path.is_file() else ""
        except OSError:
            size = ""
        meta = [f"Type:   {kind}"]
        if size:
            meta.append(f"Size:   {size}")
        meta.append("Select: " + ("✔ yes" if selected else "no"))
        lines.append("\n".join(meta))
        lines.append("")
        if path.suffix == ".enc":
            lines.append("[d] decrypt · [v] verify")
        else:
            lines.append("[Space] select · [e] encrypt")
        sidebar.update("\n".join(lines))

    def _update_status(self) -> None:
        bar = self.query_one("#status-bar", Static)
        count = len(self._tree.selected_paths)
        try:
            root = "~" + str(self.start_path.relative_to(Path.home()))
        except ValueError:
            root = str(self.start_path)
        parts = [root]
        if count:
            parts.append(f"{count} selected")
        if self._busy:
            parts.append("[reverse] working… [/reverse]")
        bar.update("  ·  ".join(parts))

    def action_toggle_select(self) -> None:
        path = self.cursor_path
        if path is not None and path.resolve() == self.start_path.resolve():
            self._log(
                "[red]✗ Cannot select the root folder — navigate inside "
                "and pick items.[/red]"
            )
            return
        self._tree.toggle_selection(self._tree.cursor_node)
        self._update_sidebar()
        self._update_status()

    def action_clear_selection(self) -> None:
        self._tree.clear_selection()
        self._update_sidebar()
        self._update_status()

    def _busy_check(self) -> bool:
        if self._busy:
            self._log("[yellow]⚠ An operation is already running…[/yellow]")
            return True
        return False

    def _start_progress(self, total: int) -> None:
        bar = self.query_one("#progress", ProgressBar)
        bar.total = max(total, 1)
        bar.update(progress=0)
        bar.display = True

    def _advance_progress(self, advance: int) -> None:
        bar = self.query_one("#progress", ProgressBar)
        bar.update(progress=bar.progress + advance)

    def _stop_progress(self) -> None:
        self.query_one("#progress", ProgressBar).display = False

    def _refresh_tree(self) -> None:
        self._tree.purge_missing()
        self._tree.reload()
        self._tree.restore_markers()
        self._update_sidebar()
        self._update_status()

    def _run_ops(self, fn) -> None:
        def wrapped() -> None:
            try:
                fn()
            finally:
                self._busy = False
                self.call_from_thread(self._refresh_tree)
                self.call_from_thread(self._update_status)

        self._busy = True
        self._update_status()
        self.run_worker(wrapped, thread=True, group="ops", exclusive=True)

    def _resolve_conflict_from_worker(self, dest: Path):
        event = threading.Event()
        answer: list = []

        def _push() -> None:
            self.push_screen(
                ConflictScreen(dest),
                lambda result: (answer.append(result), event.set()),
            )

        self.call_from_thread(_push)
        event.wait()
        if not answer:
            return None, None
        return answer[0]

    def _decrypt_resolve_dest(self, dest: Path) -> Path | None:
        action, resolved = self._resolve_conflict_from_worker(dest)
        if action == "replace":
            return dest
        if action == "rename":
            self._log(f"[dim]Saving as '{resolved.name}'.[/dim]")
            return resolved
        return None

    def _collect_targets(self, extension: str | None = None) -> list[Path]:
        selected = sorted(self._tree.selected_paths)
        if selected:
            targets = selected
        elif self.cursor_path is not None:
            targets = [self.cursor_path]
        else:
            targets = []
        if extension is not None:
            targets = [t for t in targets if t.suffix == extension]
        return [t for t in targets if t.exists()]

    def _dir_size(self, path: Path) -> int:
        if path.is_dir():
            return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        return path.stat().st_size



    def action_encrypt(self) -> None:
        if self._busy_check():
            return
        if not self._tree.selected_paths and self.cursor_path == self.start_path:
            self._log(
                "[red]✗ Cannot encrypt the root folder — select files or "
                "subfolders inside.[/red]"
            )
            return
        targets = self._collect_targets()
        if not targets:
            self._log("[red]✗ Select files or folders to encrypt first.[/red]")
            return

        jobs = [(src, default_enc_dest(src)) for src in targets]
        conflicts = sum(1 for _, dest in jobs if dest.exists())

        def _on_password(result) -> None:
            if result is None:
                self._log("[dim]Cancelled.[/dim]")
                return
            source, password = result
            if source == "generated":
                copied = copy_to_clipboard(password)
                if copied:
                    schedule_clipboard_clear(delay=30)

                def _after_gen_screen(_) -> None:
                    self._confirm_and_run(jobs, conflicts, password)

                self.push_screen(
                    GeneratedPasswordScreen(password, copied), _after_gen_screen
                )
            else:
                self._confirm_and_run(jobs, conflicts, password)

        self.push_screen(
            PasswordModal(f"Encrypt {len(targets)} item(s)", allow_generate=True),
            _on_password,
        )

    def _confirm_and_run(self, jobs, conflicts: int, password: str) -> None:
        if conflicts:

            def _on_confirm(overwrite: bool | None) -> None:
                runnable = (
                    jobs if overwrite else [j for j in jobs if not j[1].exists()]
                )
                skipped = len(jobs) - len(runnable)
                if skipped:
                    self._log(
                        f"[yellow]⚠ {skipped} destination(s) exist — skipped.[/yellow]"
                    )
                if runnable:
                    self._run_ops(lambda: self._encrypt_worker(runnable, password))

            self.push_screen(
                ConfirmScreen(f"{conflicts} destination(s) exist. Overwrite?"),
                _on_confirm,
            )
        else:
            self._run_ops(lambda: self._encrypt_worker(jobs, password))

    def _encrypt_worker(self, jobs, password: str) -> None:
        self._log("[dim]Scanning folder sizes…[/dim]")
        sized = []
        total = 0
        for src, dest in jobs:
            try:
                size = self._dir_size(src)
            except OSError as exc:
                self._log(f"[red]✗ Cannot read '{src.name}': {exc}[/red]")
                continue
            sized.append((src, dest, size))
            total += size
        if not sized:
            self.call_from_thread(self._stop_progress)
            return

        self.call_from_thread(self._start_progress, total)
        failures = 0
        for src, dest, _size in sized:
            kind = "folder" if src.is_dir() else "file"
            self._log(f"[bold]Encrypting[/bold] [cyan]{src.name}[/cyan] ({kind})…")
            try:
                sha256 = encrypt_path(
                    src,
                    password,
                    dest,
                    on_progress=lambda n: self.call_from_thread(
                        self._advance_progress, n
                    ),
                )
            except Exception as exc:
                failures += 1
                self._log(f"[red]✗ Failed to encrypt '{src.name}': {exc}[/red]")
                continue
            dest_size = dest.stat().st_size
            self._log(
                f"[green]✓ {kind.capitalize()} encrypted → {dest}"
                f" ({sizeof_fmt(dest_size)})[/green]"
            )
            self._log(f"[dim]SHA-256: {sha256}[/dim]")
        self.call_from_thread(self._stop_progress)
        if failures == 0:
            self._log("[green]All items encrypted successfully.[/green]")

    def action_decrypt(self) -> None:
        if self._busy_check():
            return
        targets = self._collect_targets(".enc")
        if len(targets) != 1:
            self._log("[red]✗ Place the cursor on a single .enc file to decrypt.[/red]")
            return

        enc = targets[0]

        def _on_password(result) -> None:
            if result is None:
                self._log("[dim]Cancelled.[/dim]")
                return
            _, password = result
            self._run_ops(lambda: self._decrypt_worker(enc, password))

        self.push_screen(PasswordModal(f"Decrypt {enc.name}"), _on_password)

    def _decrypt_worker(self, enc: Path, password: str) -> None:
        self.call_from_thread(self._start_progress, enc.stat().st_size)
        self._log(f"[bold]Decrypting[/bold] [cyan]{enc.name}[/cyan]…")

        try:
            dest = decrypt_file(
                enc,
                password,
                on_progress=lambda n: self.call_from_thread(
                    self._advance_progress, n
                ),
                resolve_dest=self._decrypt_resolve_dest,
            )
        except DestinationExistsError as e:
            self._log(
                f"[yellow]⚠ '{e}' already exists — operation cancelled.[/yellow]"
            )
            self.call_from_thread(self._stop_progress)
            return
        except ValueError as e:
            self._log(f"[red]✗ {e}[/red]")
            self.call_from_thread(self._stop_progress)
            return

        self.call_from_thread(self._stop_progress)

        if dest is None:
            self._log("[yellow]⚠ Decryption cancelled — existing file kept.[/yellow]")
            return

        kind = "Folder" if dest.is_dir() else "File"
        extra = (
            ""
            if dest.is_dir()
            else f" ({sizeof_fmt(dest.stat().st_size)})"
        )
        self._log(f"[green]✓ {kind} successfully decrypted → {dest}{extra}[/green]")



    def action_verify(self) -> None:
        if self._busy_check():
            return
        targets = self._collect_targets(".enc")
        if len(targets) != 1:
            self._log("[red]✗ Place the cursor on a single .enc file to verify.[/red]")
            return

        enc = targets[0]

        def _on_password(result) -> None:
            if result is None:
                self._log("[dim]Cancelled.[/dim]")
                return
            _, password = result
            self._run_ops(lambda: self._verify_worker(enc, password))

        self.push_screen(PasswordModal(f"Verify {enc.name}"), _on_password)

    def _verify_worker(self, enc: Path, password: str) -> None:
        self._log(f"[bold]Verifying[/bold] [cyan]{enc.name}[/cyan]…")
        try:
            original_name = verify_file(enc, password)
        except ValueError as e:
            self._log(f"[red]✗ {e}[/red]")
            return
        self._log(
            f"[green]✓ Integrity verified — original filename: {original_name}[/green]"
        )
