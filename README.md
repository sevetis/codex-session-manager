# cdx-session-manager

A lightweight Codex session manager:
- interactive TUI session list
- resume selected session
- create new session for a target directory
- delete session(s)

轻量级 Codex 会话管理器：
- 交互式 TUI 会话列表
- 恢复选中的历史会话
- 在指定目录新建会话
- 删除会话

## Why this exists / 为什么要做这个

Codex's built-in conversation management still has room for improvement: scattered entry points, no direct deletion workflow, and friction when switching projects.  
This tool provides one practical, keyboard-first control surface for day-to-day session operations.

Codex 原生对话管理在日常使用中还有不少可改进空间：会话入口分散、删除能力缺失、跨项目切换成本高，定位旧会话效率也不稳定。  
这个工具把这些高频操作收敛成统一入口，尽量减少在“找会话”和“管理上下文”上的时间消耗。

## Install

```bash
chmod +x codex_session_manager.py
cp codex_session_manager.py ~/bin/cdx
```

For fish:

```fish
fish_add_path -m $HOME/bin
```

fish 用户可将上面一行写入 `~/.config/fish/config.fish` 持久生效。

## Usage

```bash
cdx
cdx --list
cdx --new /path/to/project --prompt "start a refactor"
```

```bash
# 仅打开管理器（TUI）
cdx

# 列出会话
cdx --list

# 在指定目录新建会话（可选首条 prompt）
cdx --new /path/to/project --prompt "start a refactor"
```

## TUI keys

- `j/k` or `Up/Down`: move
- `Enter` or `o`: resume selected session
- `n`: create a new session
- `d`: delete selected session
- `r`: refresh
- `q`: quit

## TUI 快捷键

- `j/k` 或 `上/下`: 移动选中
- `Enter` 或 `o`: 恢复会话
- `n`: 新建会话
- `d`: 删除会话
- `r`: 刷新
- `q`: 退出
