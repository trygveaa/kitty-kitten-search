from kittens.tui.handler import result_handler
from kitty.boss import Boss


def main(args: list[str]) -> None:
    pass


@result_handler(no_ui=True)
def handle_result(
    args: list[str], answer: str, target_window_id: int, boss: Boss
) -> None:
    w = boss.window_id_map.get(target_window_id)
    if w is not None:
        if len(args) > 1 and args[1] != "prev":
            # Next match (downward)
            if not w.scroll_to_mark(prev=False):
                w.scroll_home()
                w.scroll_to_mark(prev=False)
        else:
            # Previous match (upward)
            if not w.scroll_to_mark():
                w.scroll_end()
                w.scroll_to_mark()
