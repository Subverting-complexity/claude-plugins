#!/usr/bin/env bash
# Print the projection of ClaudeProject.md that execute and bulk-execute load
# at the start of a run: the file with the sections only a later phase needs
# dropped. The projection is cached in .claude/projected-config.md.
#
# Run from anywhere inside the repository: it walks up to the directory
# holding .git, as repo-host.sh does. The cache is used only while it is newer
# than both ClaudeProject.md and this script, so a plugin update that changes
# which sections are dropped rebuilds it. A missing ClaudeProject.md always
# prints "ClaudeProject.md NOT FOUND", however fresh an old projection looks:
# `[ a -nt b ]` is true when b does not exist, which used to print a stale
# projection for a project whose file had been deleted.
#
# Pure POSIX shell built-ins (no awk, sed or tee), so it runs on a Windows
# bash whose PATH lacks Unix coreutils.

dir=$PWD
while [ -n "$dir" ] && [ ! -e "$dir/.git" ]; do
  parent=${dir%/*}
  [ "$parent" = "$dir" ] && dir= && break
  dir=$parent
done
root=${dir:-$PWD}
source_file="$root/ClaudeProject.md"
cache="$root/.claude/projected-config.md"

if [ ! -f "$source_file" ]; then
  rm -f "$cache" 2>/dev/null
  echo "ClaudeProject.md NOT FOUND"
  exit 0
fi

if [ -f "$cache" ] && [ "$cache" -nt "$source_file" ] && [ "$cache" -nt "$0" ]; then
  while IFS= read -r line || [ -n "$line" ]; do printf '%s\n' "$line"; done < "$cache"
  exit 0
fi

mkdir -p "$root/.claude" 2>/dev/null
drop=0
out=
while IFS= read -r line || [ -n "$line" ]; do
  line=${line%$'\r'}
  case "$line" in
    '## '*) case "$line" in
        '## Issue Types & Fields'*|'## Project Board'*|'## Story Template'*|'## Session Budget'*|'## Reference Docs'*|'## Bundled Skills'*) drop=1 ;;
        *) drop=0 ;;
      esac ;;
  esac
  [ "$drop" -eq 0 ] && out="$out$line"$'\n'
done < "$source_file"
printf '%s' "$out" > "$cache" 2>/dev/null
printf '%s' "$out"
