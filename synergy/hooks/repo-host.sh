#!/usr/bin/env bash
# SessionStart and SubagentStart hook: tells Claude which platform hosts the
# repository, so it does not reach for gh or the GitHub workflows in an Azure
# DevOps, GitLab or Bitbucket repository. It reads the git config itself
# rather than running git, which refuses a repository owned by another
# Windows user ("dubious ownership") and costs a process start on Windows.
#
# It runs at every session start and every subagent start, and a process start
# costs tens of milliseconds on Windows, so everything below is a bash
# built-in: no cat, sed, tr, awk or dirname. It also has to run under the bash
# 3.2 macOS ships, so there is no ${var,,}; nocasematch does the case folding.
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

# Git config section names, keys and host names are all case-insensitive.
shopt -s nocasematch

# The event names the working directory; fall back to the shell's own. JSON
# escapes a Windows path's backslashes, and a forward slash works in its place.
input=
[ -t 0 ] || IFS= read -r -d '' input
dir=
cwd_re='"cwd"[[:space:]]*:[[:space:]]*"(([^"\\]|\\.)*)"'
if [[ $input =~ $cwd_re ]]; then
    dir=${BASH_REMATCH[1]}
    dir=${dir//\\\\//}
fi
[ -n "$dir" ] && [ -d "$dir" ] || dir=$PWD

# Walk up to the directory holding .git. The root is the empty string, so
# "$dir/.git" is /.git there; a drive root such as C: has no slash left to
# strip, so its parent is itself and the walk ends.
dir=${dir%/}
while [ ! -e "$dir/.git" ]; do
    parent=${dir%/*}
    [ "$parent" = "$dir" ] && exit 0
    dir=$parent
done

# A worktree or submodule has a .git file naming its git directory, and a
# worktree's git directory names the shared one holding the config.
gitdir=$dir/.git
if [ -f "$gitdir" ]; then
    line=
    IFS= read -r line < "$gitdir"
    line=${line%$'\r'}
    [[ $line == gitdir:* ]] || exit 0
    gitdir=${line#*:}
    gitdir=${gitdir#"${gitdir%%[![:space:]]*}"}
    case $gitdir in /*|[A-Za-z]:*) ;; *) gitdir=$dir/$gitdir ;; esac
    if [ -f "$gitdir/commondir" ]; then
        common=
        IFS= read -r common < "$gitdir/commondir"
        common=${common%$'\r'}
        case $common in /*|[A-Za-z]:*) gitdir=$common ;; *) gitdir=$gitdir/$common ;; esac
    fi
fi
[ -f "$gitdir/config" ] || exit 0

# origin's URL, or the first remote's when there is no origin. The remote's
# name is compared with [ = ], which nocasematch leaves alone, because git
# treats a subsection name as case-sensitive.
remote_re='^\[remote[[:space:]]+"([^"]*)"\]'
url_re='^url[[:space:]]*=[[:space:]]*(.*)$'
url= first= in_remote= is_origin=
while IFS= read -r line || [ -n "$line" ]; do
    line=${line%$'\r'}
    line=${line#"${line%%[![:space:]]*}"}
    if [[ $line == \[* ]]; then
        in_remote= is_origin=
        if [[ $line =~ $remote_re ]]; then
            in_remote=1
            [ "${BASH_REMATCH[1]}" = origin ] && is_origin=1
        fi
        continue
    fi
    [ -n "$in_remote" ] && [[ $line =~ $url_re ]] || continue
    if [ -n "$is_origin" ]; then
        url=${BASH_REMATCH[1]}
        break
    fi
    [ -n "$first" ] || first=${BASH_REMATCH[1]}
done < "$gitdir/config"
[ -n "$url" ] || url=$first
[ -n "$url" ] || exit 0

# Match the host alone. The path and the user name are anybody's to choose, so
# github.com/acme/gitlab-ci-templates or gitlab-bot@github.com must not read as
# GitLab. A URL with a scheme has its host between :// and the next /; an scp
# style remote (git@host:path, or an ssh alias such as github-work:path) has it
# before the first colon; a local path has none.
case $url in
    *://*) host=${url#*://}; host=${host%%/*} ;;
    /*|.*|[A-Za-z]:[\\/]*) host= ;;
    *:*) host=${url%%:*} ;;
    *) host= ;;
esac
host=${host##*@}
host=${host%%:*}

case $host in
    *dev.azure.com*|*visualstudio.com*) say 'Repository host: Azure DevOps, not GitHub. Do not use gh or the synergy GitHub workflows for this repository; use git and Azure DevOps tools, and ask before writing to Azure DevOps.' ;;
    *gitlab*) say 'Repository host: GitLab, not GitHub. Do not use gh or the synergy GitHub workflows for this repository; use git and GitLab tools, and ask before writing to GitLab.' ;;
    *bitbucket*) say 'Repository host: Bitbucket, not GitHub. Do not use gh or the synergy GitHub workflows for this repository; use git and Bitbucket tools, and ask before writing to Bitbucket.' ;;
    *github*) say 'Repository host: GitHub.' ;;
    *) say 'Repository host: not a recognised GitHub remote. Check where this repository is hosted before using gh or the synergy GitHub workflows.' ;;
esac
