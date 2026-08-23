from pathlib import Path
from typing import ClassVar

from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label

DIALOG_CSS: ClassVar = """
Screen {
    background: $background 60%;
}
Dialog {
    width: 64;
    height: auto;
    max-height: 80%;
    border: round $primary;
    background: $panel;
    padding: 1 2;
}
DialogTitle {
    width: 1fr;
    text-style: bold;
    color: $accent;
    margin-bottom: 1;
}
Hint {
    color: $text-muted;
    margin-top: 1;
    text-align: center;
}
ButtonRow {
    height: auto;
    margin-top: 1;
    align-horizontal: right;
}
Button {
    min-width: 14;
    margin-left: 1;
}
"""


class PasswordModal(ModalScreen):
    """Password prompt.

    Dismisses with ``(source, password)`` where source is "typed" or
    "generated", or with None when cancelled. Generate only fills the
    field; the password is submitted via OK/Enter, so an accidental
    click can never silently replace a typed password.
    """

    BINDINGS: ClassVar = [("escape", "cancel", "Cancel")]

    CSS: ClassVar = DIALOG_CSS + """
    #pwd-input {
        margin-top: 1;
    }
    """

    def __init__(self, title: str, allow_generate: bool = False) -> None:
        super().__init__()
        self._title = title
        self._allow_generate = allow_generate
        self._generated = False

    def compose(self):
        with Vertical(classes="Dialog"):
            yield Label(self._title, classes="DialogTitle")
            yield Input(password=True, placeholder="Password…", id="pwd-input")
            with Horizontal(classes="ButtonRow"):
                if self._allow_generate:
                    yield Button("Generate", variant="warning", id="btn-generate")
                yield Button("Cancel", variant="default", id="btn-cancel")
                yield Button("OK", variant="primary", id="btn-ok")
            yield Label("Enter validate · Esc cancel", classes="Hint")

    def on_mount(self) -> None:
        self.query_one("#pwd-input", Input).focus()

    def _submit(self) -> None:
        value = self.query_one("#pwd-input", Input).value
        if not value:
            return
        self.dismiss(("generated" if self._generated else "typed", value))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "pwd-input":
            self._generated = False

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-ok":
            self._submit()
        elif event.button.id == "btn-generate":
            from cipher.password import generate_password

            password_input = self.query_one("#pwd-input", Input)
            password_input.value = generate_password()
            password_input.password = False
            self._generated = True
            password_input.focus()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class GeneratedPasswordScreen(ModalScreen):
    """Displays a generated password once, with clipboard note."""

    BINDINGS: ClassVar = [("escape", "close", "Close"), ("enter", "close", "Close")]

    CSS: ClassVar = DIALOG_CSS + """
    #gen-password {
        border: round $warning;
        background: $surface;
        color: $warning;
        text-style: bold;
        padding: 0 2;
        margin-top: 1;
        content-align: center middle;
    }
    #gen-note {
        color: $warning;
        margin-top: 1;
        text-align: center;
    }
    """

    def __init__(self, password: str, copied: bool) -> None:
        super().__init__()
        self._password = password
        self._copied = copied

    def compose(self):
        with Vertical(classes="Dialog"):
            yield Label(
                "🔑 Generated password — store it safely", classes="DialogTitle"
            )
            yield Label(self._password, id="gen-password")
            note = (
                "Copied to clipboard — will be cleared in 30 s."
                if self._copied
                else "Could not copy to clipboard."
            )
            yield Label(note, id="gen-note")
            with Horizontal(classes="ButtonRow"):
                yield Button("OK", variant="primary", id="btn-gen-ok")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class ConfirmScreen(ModalScreen[bool]):
    """Yes/No confirmation; dismisses with True or False.

    Focus starts on “No” so pressing Enter never overwrites by accident.
    """

    BINDINGS: ClassVar = [
        ("escape", "no", "No"),
        ("y", "yes", "Yes"),
        ("n", "no", "No"),
    ]

    CSS: ClassVar = DIALOG_CSS

    def __init__(self, message: str, danger: bool = True) -> None:
        super().__init__()
        self._message = message
        self._danger = danger

    def compose(self):
        with Vertical(classes="Dialog danger" if self._danger else "Dialog"):
            yield Label(self._message, classes="DialogTitle")
            with Horizontal(classes="ButtonRow"):
                yield Button("No", variant="default", id="btn-no")
                yield Button(
                    "Yes",
                    variant="error" if self._danger else "primary",
                    id="btn-yes",
                )
            yield Label("Y confirm · N / Esc deny", classes="Hint")

    def on_mount(self) -> None:
        self.query_one("#btn-no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-yes")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


def suggest_name(dest: Path) -> str:
    """Return a non-conflicting name like ``name (1).ext``."""
    if not dest.exists():
        return dest.name
    if dest.is_dir():
        stem, suffix = dest.name, ""
    else:
        stem, suffix = dest.stem, dest.suffix
    for i in range(1, 1000):
        candidate = f"{stem} ({i}){suffix}"
        if not (dest.parent / candidate).exists():
            return candidate
    raise ValueError("Could not find a free name (tried 999 candidates).")


class ConflictScreen(ModalScreen):
    """Three-way destination conflict resolution.

    Dismisses with ``("replace", dest)``, ``("rename", new_dest)`` or
    ``(None, None)`` when cancelled.
    """

    BINDINGS: ClassVar = [
        ("escape", "cancel", "Cancel"),
        ("enter", "rename", "Rename"),
        ("r", "rename", "Rename"),
    ]

    CSS: ClassVar = DIALOG_CSS + """
    #conflict-input {
        margin-top: 1;
    }
    Dialog.danger {
        border: round $error;
    }
    """

    def __init__(self, dest: Path) -> None:
        super().__init__()
        self._dest = dest

    def compose(self):
        with Vertical(classes="Dialog danger"):
            yield Label(
                f"'{self._dest.name}' already exists", classes="DialogTitle"
            )
            yield Input(value=suggest_name(self._dest), id="conflict-input")
            with Horizontal(classes="ButtonRow"):
                yield Button("Cancel", variant="default", id="btn-cancel")
                yield Button("Rename", variant="primary", id="btn-rename")
                yield Button(
                    "Replace",
                    variant="error",
                    id="btn-replace",
                    disabled=not self._dest.exists(),
                )
            yield Label(
                "Enter / R rename · Esc cancel", classes="Hint"
            )

    def on_mount(self) -> None:
        inp = self.query_one("#conflict-input", Input)
        inp.focus()

    def _result(self, action: str, new_path: Path | None):
        self.dismiss((action, new_path))

    def _unique_dest(self, name: str) -> Path:
        candidate = self._dest.parent / name
        if not candidate.exists():
            return candidate
        stem = Path(name).stem
        suffix = "".join(Path(name).suffixes)
        for i in range(1, 1000):
            candidate = self._dest.parent / f"{stem} ({i}){suffix}"
            if not candidate.exists():
                return candidate
        raise ValueError("Could not find a free name.")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_rename()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-rename":
            self.action_rename()
        elif event.button.id == "btn-replace":
            self._result("replace", self._dest)
        else:
            self._result(None, None)

    def action_rename(self) -> None:
        name = self.query_one("#conflict-input", Input).value.strip()
        if not name:
            return
        self._result("rename", self._unique_dest(name))

    def action_cancel(self) -> None:
        self._result(None, None)
