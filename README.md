# cdx-session-manager

A lightweight Codex session manager:
- interactive TUI session list
- resume selected session
- create new session for a target directory
- delete session(s)

## Install

```bash
chmod +x codex_session_manager.py
cp codex_session_manager.py ~/bin/cdx
```

For fish:

```fish
fish_add_path -m $HOME/bin
```

## Usage

```bash
cdx
cdx --list
cdx --new /path/to/project --prompt "start a refactor"
```

## TUI keys

- `j/k` or `Up/Down`: move
- `Enter` or `o`: resume selected session
- `n`: create a new session
- `d`: delete selected session
- `r`: refresh
- `q`: quit
