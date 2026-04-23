import json
import re
import subprocess
from gettext import gettext as _
from pathlib import Path
from subprocess import PIPE, run

from kittens.tui.handler import Handler
from kittens.tui.line_edit import LineEdit
from kittens.tui.loop import Loop
from kittens.tui.operations import (
    clear_screen,
    cursor,
    set_line_wrapping,
    set_window_title,
    styled,
)
from kitty.config import cached_values_for
from kitty.constants import kitty_exe
from kitty.key_encoding import EventType
from kitty.typing_compat import KeyEventType, ScreenSize

NON_SPACE_PATTERN = re.compile(r"\S+")
SPACE_PATTERN = re.compile(r"\s+")
SPACE_PATTERN_END = re.compile(r"\s+$")
SPACE_PATTERN_START = re.compile(r"^\s+")

NON_ALPHANUM_PATTERN = re.compile(r"[^\w\d]+")
NON_ALPHANUM_PATTERN_END = re.compile(r"[^\w\d]+$")
NON_ALPHANUM_PATTERN_START = re.compile(r"^[^\w\d]+")
ALPHANUM_PATTERN = re.compile(r"[\w\d]+")


def call_remote_control(args: list[str]) -> None:
    subprocess.run([kitty_exe(), "@", *args], capture_output=True)


def reindex(
    text: str, pattern: re.Pattern[str], right: bool = False
) -> tuple[int, int]:
    if not right:
        m = pattern.search(text)
    else:
        matches = [x for x in pattern.finditer(text) if x]
        if not matches:
            raise ValueError
        m = matches[-1]

    if not m:
        raise ValueError

    return m.span()


SCROLLMARK_FILE = Path(__file__).parent.absolute() / "scroll_mark.py"


class Search(Handler):
    def __init__(
        self, cached_values: dict[str, str], window_ids: list[str], error: str = ""
    ) -> None:
        self.cached_values = cached_values
        self.window_ids = window_ids
        self.error = error
        self.match_count: int | None = None
        self.match_index: int = 0
        self._last_counted_query: str = ""
        self._matching_lines: list[str] = []
        self.line_edit = LineEdit()
        # Migrate old single-value format to history list
        if "last_search" in cached_values and "search_history" not in cached_values:
            old = cached_values.pop("last_search")
            cached_values["search_history"] = json.dumps([old] if old else [])
        try:
            self.history: list[str] = json.loads(cached_values.get("search_history", "[]"))
            if not isinstance(self.history, list):
                self.history = []
        except (json.JSONDecodeError, TypeError):
            self.history = []
        self.history_index: int = -1
        self.saved_input: str = ""
        last_search = self.history[0] if self.history else ""
        self.line_edit.add_text(last_search)
        self.text_marked = bool(last_search)
        self.mode = cached_values.get("mode", "text")
        self.update_prompt()
        self.mark()

    def update_prompt(self) -> None:
        self.prompt = "~> " if self.mode == "regex" else "=> "

    def init_terminal_state(self) -> None:
        self.write(set_line_wrapping(False))
        self.write(set_window_title(_("Search")))

    def initialize(self) -> None:
        self.init_terminal_state()
        self.draw_screen()

    def draw_screen(self) -> None:
        self.write(clear_screen())
        if self.window_ids:
            input_text = self.line_edit.current_input
            if self.text_marked:
                self.line_edit.current_input = styled(input_text, reverse=True)
            self.line_edit.write(self.write, self.prompt)
            self.line_edit.current_input = input_text
            if self.match_count is not None:
                if self.match_count == 0:
                    count_str = styled(" [no matches]", fg="red")
                elif self.match_index > 0:
                    count_str = styled(f" [{self.match_index}/{self.match_count}]", dim=True)
                else:
                    count_str = styled(f" [{self.match_count} matches]", dim=True)
                self.write(count_str)
        with cursor(self.write):
            if self.error:
                self.print("")
                for l in self.error.split("\n"):
                    self.print(l)
            self.print("")
            self.print(styled(
                "Tab: regex  Up/Down: prev/next match  "
                "C-Up/Down: history  C-g: copy visible  "
                "A-g: copy all  Enter/Esc: close",
                dim=True,
            ))

    def refresh(self) -> None:
        self.draw_screen()
        self.mark()

    def switch_mode(self) -> None:
        if self.mode == "regex":
            self.mode = "text"
        else:
            self.mode = "regex"
        self.cached_values["mode"] = self.mode
        self.update_prompt()

    def on_text(self, text: str, in_bracketed_paste: bool = False) -> None:
        if self.text_marked:
            self.text_marked = False
            self.line_edit.clear()
        self.history_index = -1
        self.match_index = 0
        self.error = ""
        self.line_edit.on_text(text, in_bracketed_paste)
        self.refresh()

    def on_key(self, key_event: KeyEventType) -> None:
        if key_event.type == EventType.PRESS:
            # Clear temporary feedback messages on any key press
            if self.error and self.error.startswith("["):
                self.error = ""
            if (
                self.text_marked
                and key_event.key
                not in [
                    "TAB",
                    "LEFT_CONTROL",
                    "RIGHT_CONTROL",
                    "LEFT_ALT",
                    "RIGHT_ALT",
                    "LEFT_SHIFT",
                    "RIGHT_SHIFT",
                    "LEFT_SUPER",
                    "RIGHT_SUPER",
                ]
            ):
                self.text_marked = False
                self.refresh()

        if self.line_edit.on_key(key_event):
            self.refresh()
            return

        if key_event.matches("ctrl+u"):
            self.line_edit.clear()
            self.refresh()
        elif key_event.matches("ctrl+a"):
            self.line_edit.home()
            self.refresh()
        elif key_event.matches("ctrl+e"):
            self.line_edit.end()
            self.refresh()
        elif key_event.matches("ctrl+backspace") or key_event.matches("ctrl+w"):
            before, _ = self.line_edit.split_at_cursor()

            try:
                start, _ = reindex(before, SPACE_PATTERN_END, right=True)
            except ValueError:
                start = -1

            try:
                space = before[:start].rindex(" ")
            except ValueError:
                space = 0
            self.line_edit.backspace(len(before) - space)
            self.refresh()
        elif key_event.matches("ctrl+left") or key_event.matches("ctrl+b"):
            before, _ = self.line_edit.split_at_cursor()
            try:
                start, _ = reindex(before, SPACE_PATTERN_END, right=True)
            except ValueError:
                start = -1

            try:
                space = before[:start].rindex(" ")
            except ValueError:
                space = 0
            self.line_edit.left(len(before) - space)
            self.refresh()
        elif key_event.matches("ctrl+right") or key_event.matches("ctrl+f"):
            _, after = self.line_edit.split_at_cursor()
            try:
                _, end = reindex(after, SPACE_PATTERN_START)
            except ValueError:
                end = 0

            try:
                space = after[end:].index(" ") + 1
            except ValueError:
                space = len(after)
            self.line_edit.right(space)
            self.refresh()
        elif key_event.matches("alt+backspace") or key_event.matches("alt+w"):
            before, _ = self.line_edit.split_at_cursor()

            try:
                start, _ = reindex(before, NON_ALPHANUM_PATTERN_END, right=True)
            except ValueError:
                start = -1
            else:
                self.line_edit.backspace(len(before) - start)
                self.refresh()
                return

            try:
                start, _ = reindex(before, NON_ALPHANUM_PATTERN, right=True)
            except ValueError:
                self.line_edit.backspace(len(before))
                self.refresh()
                return

            self.line_edit.backspace(len(before) - (start + 1))
            self.refresh()
        elif key_event.matches("alt+left") or key_event.matches("alt+b"):
            before, _ = self.line_edit.split_at_cursor()

            try:
                start, _ = reindex(before, NON_ALPHANUM_PATTERN_END, right=True)
            except ValueError:
                start = -1
            else:
                self.line_edit.left(len(before) - start)
                self.refresh()
                return

            try:
                start, _ = reindex(before, NON_ALPHANUM_PATTERN, right=True)
            except ValueError:
                self.line_edit.left(len(before))
                self.refresh()
                return

            self.line_edit.left(len(before) - (start + 1))
            self.refresh()
        elif key_event.matches("alt+right") or key_event.matches("alt+f"):
            _, after = self.line_edit.split_at_cursor()

            try:
                _, end = reindex(after, NON_ALPHANUM_PATTERN_START)
            except ValueError:
                end = 0
            else:
                self.line_edit.right(end)
                self.refresh()
                return

            try:
                _, end = reindex(after, NON_ALPHANUM_PATTERN)
            except ValueError:
                self.line_edit.right(len(after))
                self.refresh()
                return

            self.line_edit.right(end - 1)
            self.refresh()
        elif key_event.matches("ctrl+g"):
            text = self._get_matching_lines("screen")
            if text:
                self._copy_to_clipboard(text)
                n = len(text.splitlines())
                self.error = f"[copied {n} line{'s' if n != 1 else ''}]"
            else:
                self.error = "[no matching lines]"
            self.draw_screen()
        elif key_event.matches("alt+g"):
            text = self._get_matching_lines("all")
            if text:
                self._copy_to_clipboard(text)
                n = len(text.splitlines())
                self.error = f"[copied {n} line{'s' if n != 1 else ''}]"
            else:
                self.error = "[no matching lines]"
            self.draw_screen()
        elif key_event.matches("tab"):
            self.switch_mode()
            self.refresh()
        elif key_event.matches("ctrl+up"):
            if self.history:
                if self.history_index == -1:
                    self.saved_input = self.line_edit.current_input
                if self.history_index < len(self.history) - 1:
                    self.history_index += 1
                    self.line_edit.clear()
                    self.line_edit.add_text(self.history[self.history_index])
                    self.text_marked = False
                    self.refresh()
        elif key_event.matches("ctrl+down"):
            if self.history_index > 0:
                self.history_index -= 1
                self.line_edit.clear()
                self.line_edit.add_text(self.history[self.history_index])
                self.text_marked = False
                self.refresh()
            elif self.history_index == 0:
                self.history_index = -1
                self.line_edit.clear()
                self.line_edit.add_text(self.saved_input)
                self.text_marked = False
                self.refresh()
        elif key_event.matches("up"):
            self._count_matches()
            if self.match_count and self.match_count > 0:
                if self.match_index <= 1:
                    self.match_index = self.match_count
                else:
                    self.match_index -= 1
            for match_arg in self.match_args():
                call_remote_control(["kitten", match_arg, str(SCROLLMARK_FILE)])
            self.draw_screen()
        elif key_event.matches("down"):
            self._count_matches()
            if self.match_count and self.match_count > 0:
                if self.match_index >= self.match_count:
                    self.match_index = 1
                else:
                    self.match_index += 1
            for match_arg in self.match_args():
                call_remote_control(["kitten", match_arg, str(SCROLLMARK_FILE), "next"])
            self.draw_screen()
        elif key_event.matches("enter"):
            self.quit(0)
        elif key_event.matches("esc"):
            self.quit(1)

    def on_interrupt(self) -> None:
        self.quit(1)

    def on_eot(self) -> None:
        self.quit(1)

    def on_resize(self, screen_size: ScreenSize) -> None:
        self.refresh()

    def match_args(self) -> list[str]:
        return [f"--match=id:{window_id}" for window_id in self.window_ids]

    def _get_matching_lines(self, extent: str = "screen") -> str:
        query = self.line_edit.current_input
        if not query or not self.window_ids:
            return ""
        wid = self.window_ids[0]
        try:
            result = subprocess.run(
                [kitty_exe(), "@", "get-text", f"--match=id:{wid}", f"--extent={extent}"],
                capture_output=True,
                text=True,
            )
            content = result.stdout
        except Exception:
            return ""
        lines = content.splitlines()
        if self.mode == "regex":
            flags = re.IGNORECASE if query.islower() else 0
            try:
                matched = [l for l in lines if re.search(query, l, flags)]
            except re.error:
                return ""
        else:
            if query.islower():
                matched = [l for l in lines if query in l.lower()]
            else:
                matched = [l for l in lines if query in l]
        return "\n".join(matched)

    def _copy_to_clipboard(self, text: str) -> bool:
        try:
            result = subprocess.run(
                [kitty_exe(), "+kitten", "clipboard"],
                input=text.encode(),
                capture_output=True,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _count_matches(self) -> None:
        query = self.line_edit.current_input
        if not query or not self.window_ids:
            self.match_count = None
            self._last_counted_query = ""
            self._matching_lines = []
            return
        # Skip recount if query/mode unchanged (e.g. resize, navigation)
        cache_key = f"{self.mode}:{query}"
        if cache_key == self._last_counted_query:
            return
        wid = self.window_ids[0]
        try:
            result = subprocess.run(
                [kitty_exe(), "@", "get-text", f"--match=id:{wid}", "--extent=all"],
                capture_output=True,
                text=True,
            )
            content = result.stdout
        except Exception:
            self.match_count = None
            self._matching_lines = []
            return
        # Count matching lines (not occurrences) — scroll_mark navigates by line
        lines = content.splitlines()
        if self.mode == "regex":
            flags = re.IGNORECASE if query.islower() else 0
            try:
                matched = [l for l in lines if re.search(query, l, flags)]
            except re.error:
                self.match_count = None
                self._matching_lines = []
                return
        else:
            if query.islower():
                matched = [l for l in lines if query in l.lower()]
            else:
                matched = [l for l in lines if query in l]
        self._matching_lines = matched
        self.match_count = len(matched)
        self.match_index = 0
        self._last_counted_query = cache_key

    def _create_markers(self) -> None:
        """Create marker rules: group 1 for all matches, group 3 for current line."""
        text = self.line_edit.current_input
        if not text or not self.window_ids:
            return
        match_case = "i" if text.islower() else ""
        # Always use regex type so we can combine search term + current line
        marker_type = match_case + "regex"
        search_pattern = text if self.mode == "regex" else re.escape(text)
        marker_args = [marker_type, "1", search_pattern]
        # Add group 3 for the current match line
        if self.match_index > 0 and self._matching_lines:
            idx = self.match_index - 1
            if 0 <= idx < len(self._matching_lines):
                line = self._matching_lines[idx].rstrip("\r\n")
                if line:
                    marker_args.extend(["3", f"^{re.escape(line)}$"])
        for match_arg in self.match_args():
            try:
                call_remote_control(["create-marker", match_arg] + marker_args)
            except SystemExit:
                self.remove_mark()

    def mark(self) -> None:
        if not self.window_ids:
            return
        text = self.line_edit.current_input
        if text:
            self._create_markers()
        else:
            self.remove_mark()
            self.match_count = None
            self._last_counted_query = ""
            self._matching_lines = []

    def remove_mark(self) -> None:
        for match_arg in self.match_args():
            call_remote_control(["remove-marker", match_arg])

    def quit(self, return_code: int) -> None:
        current = self.line_edit.current_input
        if current:
            # Deduplicate: remove existing occurrence, prepend
            if current in self.history:
                self.history.remove(current)
            self.history.insert(0, current)
            self.history = self.history[:50]
        self.cached_values["search_history"] = json.dumps(self.history)
        # Keep last_search for backward compat
        self.cached_values["last_search"] = current
        self.remove_mark()
        if return_code:
            for match_arg in self.match_args():
                call_remote_control(["scroll-window", match_arg, "end"])
        self.quit_loop(return_code)


def main(args: list[str]) -> None:
    error = ""
    if len(args) < 2:
        error = "Error: Window id must be provided as the first argument."
        window_ids: list[str] = []
    else:
        window_id = args[1]
        window_ids = [window_id]
        if len(args) > 2 and args[2] == "--all-windows":
            ls_output = run([kitty_exe(), "@", "ls"], stdout=PIPE)
            ls_json = json.loads(ls_output.stdout.decode())
            current_tab = None
            for os_window in ls_json:
                for tab in os_window["tabs"]:
                    for kitty_window in tab["windows"]:
                        if window_id.isdigit():
                            match = kitty_window["id"] == int(window_id)
                        else:
                            match = kitty_window["is_focused"]
                        if match:
                            current_tab = tab
            if current_tab:
                window_ids = [
                    str(w["id"])
                    for w in current_tab["windows"]
                    if not w["is_focused"]
                ]
            else:
                error = "Error: Could not find the window id provided."

    loop = Loop()
    with cached_values_for("search") as cached_values:
        handler = Search(cached_values, window_ids, error)
        loop.loop(handler)
