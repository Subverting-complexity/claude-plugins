#!/usr/bin/env bash
# SessionStart and SubagentStart hook: tells Claude which platform hosts the
# repository, so it does not reach for gh or the GitHub workflows in an Azure
# DevOps, GitLab or Bitbucket repository. It reads the git config itself
# rather than running git, which refuses a repository owned by another
# Windows user ("dubious ownership") and costs a process start on Windows.
#
# Pass SubagentStart as the first argument to get the JSON that event needs.
# Only the platform is printed, never the remote URL, which can carry a token.
# count-tokens.sh counts the longest `say` line as this hook's every-chat load,
# so every message is one literal `say '...'` line.
event=${1:-SessionStart}

say() {
    if [ "$event" = SubagentStart ]; then
        printf '{"hookSpecificOutput":{"hookEventName":"SubagentStart","additionalContext":"%s"}}\n' "$1"
    else
        printf '%s\n' "$1"
    fi
    exit 0
}

# The event names the working directory; fall back to the shell's own.
input=
[ -t 0 ] || input=$(cat)
dir=$(printf '%s' "$input" | sed -n 's/.*"cwd"[[:space:]]*:[[:space:]]*"\(\([^"\\]\|\\.\)*\)".*/\1/p' | sed 's/\\\\/\//g')
[ -n "$dir" ] && [ -d "$dir" ] || dir=$PWD

while [ ! -e "$dir/.git" ]; do
    parent=$(dirname "$dir")
    case $parent in "$dir"|.) exit 0 ;; esac
    dir=$parent
done

# A worktree or submodule has a .git file naming its git directory, and a
# worktree's git directory names the shared one holding the config.
gitdir=$dir/.git
if [ -f "$gitdir" ]; then
    gitdir=$(sed -n 's/^gitdir:[[:space:]]*//p' "$gitdir" | tr -d '\r')
    case $gitdir in /*|[A-Za-z]:*) ;; *) gitdir=$dir/$gitdir ;; esac
    if [ -f "$gitdir/commondir" ]; then
        common=$(tr -d '\r' < "$gitdir/commondir")
        case $common in /*|[A-Za-z]:*) gitdir=$common ;; *) gitdir=$gitdir/$common ;; esac
    fi
fi
[ -f "$gitdir/config" ] || exit 0

# origin's URL, or the first remote's when there is no origin.
url=$(tr -d '\r' < "$gitdir/config" | awk '
    /^[[:space:]]*\[/ { section = $0; next }
    /^[[:space:]]*url[[:space:]]*=/ && section ~ /^[[:space:]]*\[remote / {
        v = $0; sub(/^[^=]*=[[:space:]]*/, "", v)
        if (section ~ /"origin"\]/) { print v; found = 1; exit }
        if (first == "") first = v
    }
    END { if (!found && first != "") print first }
' | tr '[:upper:]' '[:lower:]')

case $url in
    "") exit 0 ;;
    *dev.azure.com*|*visualstudio.com*) say 'Repository host: Azure DevOps, not GitHub. Do not use gh or the synergy GitHub workflows for this repository; use git and Azure DevOps tools, and ask before writing to Azure DevOps.' ;;
    *gitlab*) say 'Repository host: GitLab, not GitHub. Do not use gh or the synergy GitHub workflows for this repository; use git and GitLab tools, and ask before writing to GitLab.' ;;
    *bitbucket*) say 'Repository host: Bitbucket, not GitHub. Do not use gh or the synergy GitHub workflows for this repository; use git and Bitbucket tools, and ask before writing to Bitbucket.' ;;
    *github*) say 'Repository host: GitHub.' ;;
    *) say 'Repository host: not a recognised GitHub remote. Check where this repository is hosted before using gh or the synergy GitHub workflows.' ;;
esac
