# fish completions for the geth command (loaded by env.fish).

function __geth_tokens  # the words before the cursor: geth <command> <arguments...>
    commandline -xpc 2>/dev/null; or commandline -opc
end

function __geth_at --argument-names cmd n  # true when completing argument n (from 0) of `geth <cmd>`
    set -l t (__geth_tokens)
    test (count $t) -ge 2; and test "$t[2]" = "$cmd"; and test (math (count $t) - 2) -eq $n
end

function __geth_lab_at --argument-names cmd n  # the same for `geth lab <cmd>`
    set -l t (__geth_tokens)
    test (count $t) -ge 3; and test "$t[2]" = lab; and test "$t[3]" = "$cmd"; and test (math (count $t) - 3) -eq $n
end

function __geth_plan_from  # true when completing the upstream run of `geth plan --from`
    set -l t (__geth_tokens)
    test (count $t) -eq 3; and test "$t[2]" = plan; and test "$t[3]" = --from
end

function __geth_runs --argument-names want  # run names, with their pipeline as description
    set -q GETH_RUNS_DIR; or return
    for d in $GETH_RUNS_DIR/*/
        set d (string trim -r -c / -- $d)
        test -f $d/question.txt; or continue
        switch "$want"
            case planned
                test -f $d/plan_pipeline.txt; or continue
            case approved
                test -f $d/APPROVED; or continue
            case succeeded
                test -f $d/outcome.txt; and string match -q 'succeeded: true' <$d/outcome.txt; or continue
        end
        set -l pipeline -
        test -f $d/plan_pipeline.txt; and set pipeline (string trim <$d/plan_pipeline.txt)
        printf '%s\t%s\n' (string replace -r '.*/' '' -- $d) $pipeline
    end
end

function __geth_lab_runs  # lab run names, with their arm as description
    set -q GETH_RUNS_DIR; or return
    for d in $GETH_RUNS_DIR/lab/*/
        set d (string trim -r -c / -- $d)
        set -l arm -
        test -f $d/lab_arm.txt; and set arm (string trim <$d/lab_arm.txt)
        printf '%s\t%s\n' (string replace -r '.*/' '' -- $d) $arm
    end
end

set -l __geth_commands plan show approve run status list doctor version lab
complete -c geth -f
complete -c geth -n "not __fish_seen_subcommand_from $__geth_commands" -a plan -d 'Planner agent writes a plan'
complete -c geth -n "not __fish_seen_subcommand_from $__geth_commands" -a show -d 'Print a plan and its check'
complete -c geth -n "not __fish_seen_subcommand_from $__geth_commands" -a approve -d 'Approve a plan'
complete -c geth -n "not __fish_seen_subcommand_from $__geth_commands" -a run -d 'Run an approved plan'
complete -c geth -n "not __fish_seen_subcommand_from $__geth_commands" -a status -d 'Outcome, report check, attempts'
complete -c geth -n "not __fish_seen_subcommand_from $__geth_commands" -a list -d 'All runs and where they stand'
complete -c geth -n "not __fish_seen_subcommand_from $__geth_commands" -a doctor -d 'Check the installation'
complete -c geth -n "not __fish_seen_subcommand_from $__geth_commands" -a version -d "Print Geth's version"
complete -c geth -n "not __fish_seen_subcommand_from $__geth_commands" -a lab -d 'EXPERIMENTAL agent-designed analyses'

# geth plan <data_dir> "<question>" <name>   |   geth plan --from <run> "<question>" <name>
complete -c geth -n '__geth_at plan 0' -a '(__fish_complete_directories (commandline -ct) "data folder")'
complete -c geth -n '__geth_at plan 0' -l from -d 'Follow-up analysis of a finished run'
complete -c geth -n __geth_plan_from -a '(__geth_runs succeeded)'

complete -c geth -n '__geth_at show 0' -a '(__geth_runs planned)'
complete -c geth -n '__geth_at status 0' -a '(__geth_runs)'
complete -c geth -n '__geth_at approve 0' -a '(__geth_runs planned)'
complete -c geth -n '__geth_at approve 1' -l yes -d 'Approve without the prompt'
complete -c geth -n '__geth_at run 0' -a '(__geth_runs approved)'
complete -c geth -n '__geth_at run 1' -l detach -d 'Run in the background'

# geth lab design <data_dir> "<question>" <name> [--no-skill]   |   geth lab show <name>   |   geth lab list
complete -c geth -n '__geth_at lab 0' -a design -d 'Designer agent writes an analysis design'
complete -c geth -n '__geth_at lab 0' -a show -d 'Print a design and its check'
complete -c geth -n '__geth_at lab 0' -a list -d 'All lab runs and where they stand'
complete -c geth -n '__geth_lab_at design 0' -a '(__fish_complete_directories (commandline -ct) "benchmark data folder")'
complete -c geth -n '__geth_lab_at design 3' -l no-skill -d 'Designer without the best-practice skill'
complete -c geth -n '__geth_lab_at show 0' -a '(__geth_lab_runs)'
