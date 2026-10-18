#!/usr/bin/env bash
# Used by env.fish: sources env.sh in bash and prints what it changed in the environment, as NUL-separated
# records ("set" NAME VALUE, or "unset" NAME), so another shell gets exactly bash's settings and the site
# configuration stays one bash file. Messages from env.sh go to stderr; the exit status is env.sh's.
declare -A before after
while IFS= read -r -d '' kv; do before[${kv%%=*}]=${kv#*=}; done < <(env -0)
# shellcheck source=/dev/null
source "$1" >&2 || exit 1
while IFS= read -r -d '' kv; do after[${kv%%=*}]=${kv#*=}; done < <(env -0)
for k in "${!after[@]}"; do
    case $k in BASH_FUNC_*|SHLVL|_|PWD|OLDPWD) continue ;; esac
    [[ -v "before[$k]" && "${before[$k]}" == "${after[$k]}" ]] && continue
    printf 'set\0%s\0%s\0' "$k" "${after[$k]}"
done
for k in "${!before[@]}"; do
    case $k in BASH_FUNC_*|SHLVL|_|PWD|OLDPWD) continue ;; esac
    [[ -v "after[$k]" ]] || printf 'unset\0%s\0' "$k"
done
