import asyncio
from pathlib import Path

import pytest

from cipher.tui.app import CipherApp
from cipher.tui.modals import PasswordModal

PASSWORD = "StrongPass1!"


async def _wait_for(predicate, timeout: float = 5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


def _node_for(tree, path: Path):
    for node in tree.walk_nodes():
        data = node.data
        if data is None:
            continue
        node_path = Path(data.path) if hasattr(data, "path") else Path(str(data))
        if node_path == path:
            return node
    return None


async def _wait_tree_loaded(pilot, app, path: Path):
    assert await _wait_for(lambda: _node_for(app._tree, path) is not None)


def _select(app, path: Path):
    node = _node_for(app._tree, path)
    assert node is not None, f"node not found in tree: {path}"
    app._tree.toggle_selection(node)


async def _reload_and_select(pilot, app, path: Path):
    app._tree.reload()
    assert await _wait_for(lambda: _node_for(app._tree, path) is not None)
    _select(app, path)


def _answer_password_modal(app, result):
    screen = app.screen
    assert isinstance(screen, PasswordModal), f"unexpected screen {screen!r}"
    screen.dismiss(result)


def _log_text(app) -> str:
    return "\n".join(
        str(segment.text) for line in app.query_one("#log").lines for segment in line
    )


@pytest.mark.asyncio
async def test_encrypt_and_decrypt_roundtrip(tmp_path):
    src = tmp_path / "hello.txt"
    src.write_bytes(b"Hello TUI!")

    app = CipherApp(start_path=tmp_path)
    async with app.run_test() as pilot:
        await _wait_tree_loaded(pilot, app, src)

        _select(app, src)
        app.action_encrypt()
        await pilot.pause()
        _answer_password_modal(app, ("typed", PASSWORD))

        assert await _wait_for(lambda: (tmp_path / "hello.enc").exists())
        enc = tmp_path / "hello.enc"

        # decrypt back
        src.unlink()
        await _reload_and_select(pilot, app, enc)
        app.action_decrypt()
        await pilot.pause()
        _answer_password_modal(app, ("typed", PASSWORD))

        assert await _wait_for(lambda: src.exists())


@pytest.mark.asyncio
async def test_verify_reports_original_name(tmp_path):
    src = tmp_path / "doc.txt"
    src.write_bytes(b"important")

    app = CipherApp(start_path=tmp_path)
    async with app.run_test() as pilot:
        await _wait_tree_loaded(pilot, app, src)

        _select(app, src)
        app.action_encrypt()
        await pilot.pause()
        _answer_password_modal(app, ("typed", PASSWORD))
        assert await _wait_for(lambda: (tmp_path / "doc.enc").exists())

        await _reload_and_select(pilot, app, tmp_path / "doc.enc")
        app.action_verify()
        await pilot.pause()
        _answer_password_modal(app, ("typed", PASSWORD))
        assert await _wait_for(lambda: "Integrity verified" in _log_text(app))

        assert "doc.txt" in _log_text(app)


@pytest.mark.asyncio
async def test_wrong_password_decrypt_shows_error(tmp_path):
    src = tmp_path / "secret.txt"
    src.write_bytes(b"data")

    app = CipherApp(start_path=tmp_path)
    async with app.run_test() as pilot:
        await _wait_tree_loaded(pilot, app, src)

        _select(app, src)
        app.action_encrypt()
        await pilot.pause()
        _answer_password_modal(app, ("typed", PASSWORD))
        assert await _wait_for(lambda: (tmp_path / "secret.enc").exists())

        src.unlink()
        await _reload_and_select(pilot, app, tmp_path / "secret.enc")
        app.action_decrypt()
        await pilot.pause()
        _answer_password_modal(app, ("typed", "WrongPass1!"))
        assert await _wait_for(
            lambda: "Wrong password or file has been tampered with." in _log_text(app)
        )


@pytest.mark.asyncio
async def test_cancel_password_modal_does_nothing(tmp_path):
    src = tmp_path / "file.txt"
    src.write_bytes(b"x")

    app = CipherApp(start_path=tmp_path)
    async with app.run_test() as pilot:
        await _wait_tree_loaded(pilot, app, src)

        _select(app, src)
        app.action_encrypt()
        await pilot.pause()
        _answer_password_modal(app, None)
        await pilot.pause(0.3)

        assert not (tmp_path / "file.enc").exists()


@pytest.mark.asyncio
async def test_generate_fills_field_and_requires_explicit_submit(tmp_path):
    src = tmp_path / "gen.txt"
    src.write_bytes(b"gen")

    app = CipherApp(start_path=tmp_path)
    async with app.run_test() as pilot:
        await _wait_tree_loaded(pilot, app, src)

        _select(app, src)
        app.action_encrypt()
        await pilot.pause()

        from cipher.tui.modals import PasswordModal

        modal = app.screen
        assert isinstance(modal, PasswordModal)

        await pilot.click("#btn-generate")
        await pilot.pause()
        password_input = modal.query_one("#pwd-input")
        filled = password_input.value
        assert len(filled) >= 12

        password_input.value = "MyOwnPassword1!"
        modal._submit()
        await pilot.pause()

        enc = tmp_path / "gen.enc"
        assert await _wait_for(lambda: enc.exists())
        log_text = _log_text(app)
        assert "Generated password" not in log_text


@pytest.mark.asyncio
async def test_encrypt_existing_destination_conflict(tmp_path):
    src = tmp_path / "data.txt"
    src.write_bytes(b"data")
    enc = tmp_path / "data.enc"
    enc.write_bytes(b"old content")

    app = CipherApp(start_path=tmp_path)
    async with app.run_test() as pilot:
        await _wait_tree_loaded(pilot, app, src)

        _select(app, src)
        app.action_encrypt()
        await pilot.pause()
        _answer_password_modal(app, ("typed", PASSWORD))
        await pilot.pause()

        from cipher.tui.modals import ConfirmScreen

        assert isinstance(app.screen, ConfirmScreen)
        app.screen.dismiss(False)
        await pilot.pause(0.3)

        # destination untouched
        assert enc.read_bytes() == b"old content"


@pytest.mark.asyncio
async def test_dotfiles_are_hidden(tmp_path):
    visible = tmp_path / "visible.txt"
    visible.write_bytes(b"v")
    hidden_file = tmp_path / ".hidden.txt"
    hidden_file.write_bytes(b"h")
    hidden_dir = tmp_path / ".hiddendir"
    hidden_dir.mkdir()

    app = CipherApp(start_path=tmp_path)
    async with app.run_test():
        assert await _wait_for(lambda: _node_for(app._tree, visible) is not None)

        def _shown(path):
            return _node_for(app._tree, path) is not None

        assert not _shown(hidden_file)
        assert not _shown(hidden_dir)


@pytest.mark.asyncio
async def test_tree_reloads_after_encrypt(tmp_path):
    src = tmp_path / "fresh.txt"
    src.write_bytes(b"fresh")

    app = CipherApp(start_path=tmp_path)
    async with app.run_test() as pilot:
        await _wait_tree_loaded(pilot, app, src)

        _select(app, src)
        app.action_encrypt()
        await pilot.pause()
        _answer_password_modal(app, ("typed", PASSWORD))

        enc = tmp_path / "fresh.enc"
        assert await _wait_for(lambda: enc.exists())
        assert await _wait_for(
            lambda: _node_for(app._tree, enc) is not None, timeout=5.0
        )


@pytest.mark.asyncio
async def test_decrypt_refused_overwrite_does_not_crash(tmp_path):
    src = tmp_path / "keep.txt"
    src.write_bytes(b"original")

    app = CipherApp(start_path=tmp_path)
    async with app.run_test() as pilot:
        await _wait_tree_loaded(pilot, app, src)

        _select(app, src)
        app.action_encrypt()
        await pilot.pause()
        _answer_password_modal(app, ("typed", PASSWORD))
        assert await _wait_for(lambda: (tmp_path / "keep.enc").exists())

        src.write_bytes(b"modified in place")
        await _reload_and_select(pilot, app, tmp_path / "keep.enc")
        app.action_decrypt()
        await pilot.pause()
        _answer_password_modal(app, ("typed", PASSWORD))
        await pilot.pause()

        from cipher.tui.modals import ConflictScreen

        assert isinstance(app.screen, ConflictScreen)
        app.screen.dismiss((None, None))
        await pilot.pause(0.5)

        assert src.read_bytes() == b"modified in place"
        log_text = _log_text(app)
        assert "cancelled" in log_text.lower()

        app.action_verify()
        await pilot.pause()
        assert isinstance(app.screen, PasswordModal)


@pytest.mark.asyncio
async def test_space_selects_when_tree_focused(tmp_path):
    folder = tmp_path / "sub"
    folder.mkdir()
    (folder / "inner.txt").write_text("i")

    app = CipherApp(start_path=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause(0.5)
        app.set_focus(app._tree)

        await pilot.press("down")
        await pilot.press("space")
        await pilot.pause()

        expected = app.cursor_path
        assert expected is not None and expected != tmp_path
        assert app._tree.selected_paths == {expected}
        assert app.focused is app._tree


@pytest.mark.asyncio
async def test_root_folder_selection_refused(tmp_path):
    src = tmp_path / "a.txt"
    src.write_bytes(b"a")

    app = CipherApp(start_path=tmp_path)
    async with app.run_test() as pilot:
        await _wait_tree_loaded(pilot, app, src)
        app.set_focus(app._tree)

        await pilot.press("space")
        await pilot.pause()
        assert not app._tree.selected_paths
        assert "Cannot select the root folder" in _log_text(app)

        app.action_encrypt()
        await pilot.pause()
        assert "Cannot encrypt the root folder" in _log_text(app)


@pytest.mark.asyncio
async def test_clear_activity_via_key_and_button(tmp_path):
    src = tmp_path / "a.txt"
    src.write_bytes(b"a")

    app = CipherApp(start_path=tmp_path)
    async with app.run_test() as pilot:
        await _wait_tree_loaded(pilot, app, src)

        startup_text = _log_text(app)
        assert "Welcome to cipher" in startup_text
        assert "Space: select" not in startup_text
        assert len(app.query_one("#log").lines) == 1

        app.action_clear_activity()
        await pilot.pause()
        text = _log_text(app)
        assert "Welcome to cipher" in text
        assert "Space: select" not in text
        assert len(app.query_one("#log").lines) == 1

        await pilot.press("x")
        await pilot.pause()
        assert "Welcome to cipher" in _log_text(app)

        await pilot.click("#btn-clear-log")
        await pilot.pause()
        assert "Welcome to cipher" in _log_text(app)


@pytest.mark.asyncio
async def test_enter_expands_folder_without_selecting(tmp_path):
    folder = tmp_path / "big"
    folder.mkdir()
    (folder / "inner.txt").write_text("i")

    app = CipherApp(start_path=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause(0.5)
        app.set_focus(app._tree)

        await pilot.press("down")
        await pilot.press("down")
        await pilot.pause()
        assert app.cursor_path == folder

        folder_node = _node_for(app._tree, folder)
        assert not folder_node.is_expanded

        await pilot.press("enter")
        assert await _wait_for(
            lambda: (_node_for(app._tree, folder / "inner.txt") is not None)
        )
        assert not app._tree.selected_paths


@pytest.mark.asyncio
async def test_ctrl_p_does_not_open_palette(tmp_path):
    src = tmp_path / "a.txt"
    src.write_bytes(b"a")

    app = CipherApp(start_path=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause(0.5)
        from textual.command import CommandPalette

        await pilot.press("ctrl+p")
        await pilot.pause(0.3)
        assert not isinstance(app.screen, CommandPalette)
        assert not any(
            isinstance(s, CommandPalette)
            for s in app.screen_stack
            if s is not app.screen
        )


@pytest.mark.asyncio
async def test_k_toggles_help_panel(tmp_path):
    src = tmp_path / "a.txt"
    src.write_bytes(b"a")

    app = CipherApp(start_path=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause(0.5)

        from textual.widgets import HelpPanel

        assert not app.screen.query(HelpPanel)
        await pilot.press("k")
        await pilot.pause()
        assert app.screen.query(HelpPanel)

        await pilot.press("k")
        await pilot.pause()
        assert not app.screen.query(HelpPanel)


@pytest.mark.asyncio
async def test_password_modal_shows_immediately_for_big_folder(tmp_path):
    folder = tmp_path / "many"
    folder.mkdir()
    for i in range(2000):
        (folder / f"f{i}.txt").write_text("x" * 100)

    app = CipherApp(start_path=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _wait_tree_loaded(pilot, app, folder)

        _select(app, folder)
        app.action_encrypt()
        await pilot.pause()

        from cipher.tui.modals import PasswordModal

        assert isinstance(app.screen, PasswordModal)


@pytest.mark.asyncio
async def test_decrypt_conflict_rename(tmp_path):
    src = tmp_path / "doc.txt"
    src.write_bytes(b"v1")

    app = CipherApp(start_path=tmp_path)
    async with app.run_test() as pilot:
        await _wait_tree_loaded(pilot, app, src)

        _select(app, src)
        app.action_encrypt()
        await pilot.pause()
        _answer_password_modal(app, ("typed", PASSWORD))
        assert await _wait_for(lambda: (tmp_path / "doc.enc").exists())

        await _reload_and_select(pilot, app, tmp_path / "doc.enc")
        app.action_decrypt()
        await pilot.pause()
        _answer_password_modal(app, ("typed", PASSWORD))

        from cipher.tui.modals import ConflictScreen

        assert await _wait_for(lambda: isinstance(app.screen, ConflictScreen))
        conflict = app.screen
        suggested = conflict.query_one("#conflict-input").value
        assert suggested == "doc (1).txt"

        conflict.dismiss(("rename", tmp_path / suggested))
        renamed = tmp_path / "doc (1).txt"
        assert await _wait_for(lambda: renamed.exists())
        assert renamed.read_bytes() == b"v1"
        assert src.read_bytes() == b"v1"
        assert "Saving as 'doc (1).txt'" in _log_text(app)


@pytest.mark.asyncio
async def test_selection_markers_restored_after_reload(tmp_path):
    src = tmp_path / "marked.txt"
    src.write_bytes(b"x")

    app = CipherApp(start_path=tmp_path)
    async with app.run_test() as pilot:
        await _wait_tree_loaded(pilot, app, src)
        app.set_focus(app._tree)
        assert app.focused is app._tree

        _select(app, src)
        app._tree.reload()
        assert await _wait_for(
            lambda: _node_for(app._tree, src) is not None
        )
        app._tree.restore_markers()

        node = _node_for(app._tree, src)
        assert str(node.label).endswith("  ✔")
        assert app._tree.selected_paths == {src}

        await pilot.press("c")
        await pilot.pause()
        assert not app._tree.selected_paths
        assert not str(_node_for(app._tree, src).label).endswith("  ✔")
