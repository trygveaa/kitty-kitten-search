# Search kitten for kitty

[Kitten](https://sw.kovidgoyal.net/kitty/#kittens) for the [kitty terminal emulator](https://sw.kovidgoyal.net/kitty/) providing live incremental search in the terminal history.

![Demo](https://user-images.githubusercontent.com/601966/78996982-09c42c80-7b46-11ea-9cb2-d338b846ab87.gif)

## Installation

Place the two `.py` files in this repo (`search.py` and `scroll_mark.py`) in the same directory as `kitty.conf`.

Map a key to launch the kitten. E.g. for `kitty_mod+/` add this to `kitty.conf`:

```
map kitty_mod+/      launch --allow-remote-control kitty +kitten search.py @active-kitty-window-id
```

## Usage

Pressing the key you mapped will open a window where you can type your search. The search is performed immediately as you type each key, however currently it does not scroll to a match automatically if it is outside of the current content shown.

These keys can be used to control the kitten:

- Up/down arrow: Scroll to previous/next match
- Tab: Switch between literal match and regex match
- Ctrl-u: Clear the query
- Ctrl-a/e: Go to the beginning/end of the query
- Enter: Exit the kitten and keep the current scroll position
- Esc: Exit the kitten and scroll to the bottom of the history
