#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_BIN_DIR="${TARGET_BIN_DIR:-$HOME/.local/bin}"
if [ -d "$HOME/bin" ]; then
  TARGET_BIN_DIR="$HOME/bin"
fi
TARGET_CMD="$TARGET_BIN_DIR/cdx"

mkdir -p "$TARGET_BIN_DIR"

cat > "$TARGET_CMD" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec "$ROOT_DIR/codex_session_manager.py" "\$@"
EOF
chmod +x "$TARGET_CMD"

append_if_missing() {
  local file="$1"
  local line="$2"
  mkdir -p "$(dirname "$file")"
  touch "$file"
  if ! grep -qF "$line" "$file"; then
    printf "\n%s\n" "$line" >> "$file"
  fi
}

if [ "$TARGET_BIN_DIR" = "$HOME/bin" ]; then
  append_if_missing "$HOME/.bashrc" 'export PATH="$HOME/bin:$PATH"'
  append_if_missing "$HOME/.zshrc" 'export PATH="$HOME/bin:$PATH"'
  append_if_missing "$HOME/.config/fish/config.fish" 'fish_add_path -m $HOME/bin'
else
  append_if_missing "$HOME/.bashrc" 'export PATH="$HOME/.local/bin:$PATH"'
  append_if_missing "$HOME/.zshrc" 'export PATH="$HOME/.local/bin:$PATH"'
  append_if_missing "$HOME/.config/fish/config.fish" 'fish_add_path -m $HOME/.local/bin'
fi

printf "Installed cdx -> %s\n" "$TARGET_CMD"
printf "Repo path: %s\n" "$ROOT_DIR"
printf "Restart shell or run: source ~/.bashrc  (or source ~/.zshrc / source ~/.config/fish/config.fish)\n"
