#!/usr/bin/env bash
# scripts/data-sync.sh — manage shared data directories for Git Bash worktrees.
set -euo pipefail

command="${1:-}"
if [[ $# -gt 0 ]]; then
  shift
fi

link_runtime=false
for arg in "$@"; do
  case "$arg" in
    --runtime) link_runtime=true ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 2
      ;;
  esac
done

usage() {
  cat <<'EOF'
Usage:
  bash scripts/data-sync.sh link [--runtime]
  bash scripts/data-sync.sh unlink [--runtime]
  bash scripts/data-sync.sh status
  bash scripts/data-sync.sh init-worktree [--runtime]
EOF
}

require_windows() {
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) ;;
    *)
      echo "This script supports Git Bash on Windows only." >&2
      exit 2
      ;;
  esac
}

require_windows_worktree_paths() {
  case "$PWD" in
    /mnt/*)
      echo "This script must run under Git Bash / Git for Windows, not WSL bash, because this worktree uses Windows Git metadata." >&2
      exit 2
      ;;
  esac
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
require_windows_worktree_paths
git_worktree_output=""
git_worktree_status=0
if ! git_worktree_output="$(git -C "$repo_root" worktree list --porcelain 2>&1)"; then
  git_worktree_status=$?
  echo "Error: git worktree discovery failed for repo root: $repo_root" >&2
  printf '%s\n' "$git_worktree_output" >&2
  exit "$git_worktree_status"
fi
main_repo_raw="$(printf '%s\n' "$git_worktree_output" | awk '/^worktree / { print substr($0, 10); exit }')"
if [[ -z "$main_repo_raw" ]]; then
  echo "Error: cannot determine main repository path from git worktree list for repo root: $repo_root" >&2
  exit 1
fi

current_root="$(cd "$repo_root" && pwd)"
main_root="$(cd "$main_repo_raw" 2>/dev/null && pwd)" || {
  echo "Error: main worktree path not accessible: $main_repo_raw" >&2
  exit 1
}

in_main_repo=false
if [[ "$current_root" == "$main_root" ]]; then
  in_main_repo=true
fi

to_windows_path() {
  cygpath -w "$1"
}

powershell_junction() {
  powershell.exe -NoProfile -Command "$1"
}

ps_quote() {
  printf "%s" "$1" | sed "s/'/''/g"
}

junction_exists() {
  local path win_path escaped
  path="$1"
  win_path="$(to_windows_path "$path")"
  escaped="$(ps_quote "$win_path")"
  powershell_junction "\
    \$item = Get-Item -LiteralPath '$escaped' -Force -ErrorAction SilentlyContinue; \
    if (\$null -eq \$item) { exit 1 } \
    if (\$item.LinkType -eq 'Junction') { exit 0 } \
    exit 1"
}

junction_target() {
  local path win_path escaped
  path="$1"
  win_path="$(to_windows_path "$path")"
  escaped="$(ps_quote "$win_path")"
  powershell_junction "\
    \$item = Get-Item -LiteralPath '$escaped' -Force -ErrorAction Stop; \
    if (\$item.LinkType -ne 'Junction') { exit 12 } \
    \$target = (\$item.Target | Select-Object -First 1); \
    [Console]::WriteLine(\$target)"
}

path_exists() {
  local path win_path escaped
  path="$1"
  win_path="$(to_windows_path "$path")"
  escaped="$(ps_quote "$win_path")"
  powershell_junction "\
    if (Test-Path -LiteralPath '$escaped') { exit 0 } \
    exit 1"
}

path_is_directory() {
  local path win_path escaped
  path="$1"
  win_path="$(to_windows_path "$path")"
  escaped="$(ps_quote "$win_path")"
  powershell_junction "\
    \$item = Get-Item -LiteralPath '$escaped' -Force -ErrorAction SilentlyContinue; \
    if (\$null -eq \$item) { exit 1 } \
    if (\$item.PSIsContainer) { exit 0 } \
    exit 1"
}

create_junction() {
  local target link win_target win_link escaped_target escaped_link
  target="$1"
  link="$2"
  win_target="$(to_windows_path "$target")"
  win_link="$(to_windows_path "$link")"
  escaped_target="$(ps_quote "$win_target")"
  escaped_link="$(ps_quote "$win_link")"
  powershell_junction "New-Item -ItemType Junction -Path '$escaped_link' -Target '$escaped_target' -Force | Out-Null"
}

remove_junction() {
  local link win_link escaped_link
  link="$1"
  win_link="$(to_windows_path "$link")"
  escaped_link="$(ps_quote "$win_link")"
  powershell_junction "[System.IO.Directory]::Delete('$escaped_link')"
}

ensure_parent_directory() {
  mkdir -p "$(dirname "$1")"
}

print_status() {
  local name state detail
  name="$1"
  state="$2"
  detail="${3:-}"
  if [[ -n "$detail" ]]; then
    printf '  %s: %s (%s)\n' "$name" "$state" "$detail"
  else
    printf '  %s: %s\n' "$name" "$state"
  fi
}

expected_target_for() {
  local name
  name="$1"
  printf '%s/data/%s\n' "$main_root" "$name"
}

link_path_for() {
  local name
  name="$1"
  printf '%s/data/%s\n' "$repo_root" "$name"
}

classify_path() {
  local name link_path expected_target actual_target
  name="$1"
  link_path="$(link_path_for "$name")"
  expected_target="$(expected_target_for "$name")"

  if ! path_exists "$expected_target"; then
    print_status "$name" "source-missing" "$expected_target"
    return 0
  fi

  if junction_exists "$link_path"; then
    actual_target="$(junction_target "$link_path")"
    if [[ "$actual_target" == "$(to_windows_path "$expected_target")" ]]; then
      print_status "$name" "linked-ok" "$actual_target"
    else
      print_status "$name" "linked-wrong-target" "$actual_target"
    fi
    return 0
  fi

  if path_exists "$link_path"; then
    print_status "$name" "local" "$link_path"
    return 0
  fi

  print_status "$name" "missing"
}

ensure_can_link() {
  local name link_path expected_target actual_target
  name="$1"
  link_path="$(link_path_for "$name")"
  expected_target="$(expected_target_for "$name")"

  if ! path_exists "$expected_target"; then
    echo "$name: source-missing ($expected_target)" >&2
    exit 1
  fi

  if junction_exists "$link_path"; then
    actual_target="$(junction_target "$link_path")"
    if [[ "$actual_target" == "$(to_windows_path "$expected_target")" ]]; then
      print_status "$name" "linked-ok" "$actual_target"
      return 1
    fi
    echo "$name: linked-wrong-target ($actual_target)" >&2
    exit 1
  fi

  if path_exists "$link_path"; then
    if path_is_directory "$link_path"; then
      echo "$name: refusing to replace real directory ($link_path)" >&2
    else
      echo "$name: refusing to replace real file ($link_path)" >&2
    fi
    exit 1
  fi

  return 0
}

ensure_can_unlink() {
  local name link_path
  name="$1"
  link_path="$(link_path_for "$name")"

  if junction_exists "$link_path"; then
    return 0
  fi

  if path_exists "$link_path"; then
    echo "$name: refusing to remove non-junction path ($link_path)" >&2
    exit 1
  fi

  return 1
}

link_one() {
  local name link_path expected_target
  name="$1"
  link_path="$(link_path_for "$name")"
  expected_target="$(expected_target_for "$name")"

  if ! ensure_can_link "$name"; then
    return 0
  fi

  ensure_parent_directory "$link_path"
  create_junction "$expected_target" "$link_path"
  print_status "$name" "linked-ok" "$(to_windows_path "$expected_target")"
}

unlink_one() {
  local name link_path
  name="$1"
  link_path="$(link_path_for "$name")"

  if ! ensure_can_unlink "$name"; then
    return 0
  fi

  remove_junction "$link_path"
  print_status "$name" "missing"
}

status_all() {
  echo "Main repo:  $main_root"
  echo "Worktree:   $current_root"
  echo ""
  echo "Data link status:"
  classify_path "models"
  classify_path "runtime"
}

run_link() {
  if $in_main_repo; then
    echo "Already in main repository ($main_root) — no linking needed."
    exit 0
  fi

  echo "Main repo:  $main_root"
  echo "Worktree:   $current_root"
  echo ""
  echo "Link results:"
  link_one "models"
  if $link_runtime; then
    link_one "runtime"
  else
    print_status "runtime" "unchanged" "link skipped; use --runtime"
  fi
}

run_unlink() {
  if $in_main_repo; then
    echo "Already in main repository ($main_root) — no unlinking needed."
    exit 0
  fi

  echo "Main repo:  $main_root"
  echo "Worktree:   $current_root"
  echo ""
  echo "Unlink results:"
  unlink_one "models"
  if $link_runtime; then
    unlink_one "runtime"
  else
    print_status "runtime" "unchanged" "unlink skipped; use --runtime"
  fi
}

run_init_worktree() {
  run_link
}

require_windows

case "$command" in
  link)
    run_link
    ;;
  unlink)
    run_unlink
    ;;
  status)
    status_all
    ;;
  init-worktree)
    run_init_worktree
    ;;
  ""|-h|--help|help)
    usage
    ;;
  *)
    echo "Unknown command: $command" >&2
    usage >&2
    exit 2
    ;;
esac
