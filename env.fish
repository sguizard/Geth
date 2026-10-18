# Geth environment for fish: source this file before using Geth.
#   source /path/to/Geth/env.fish
# It runs env.sh in bash and brings the result into fish, so the site configuration (site/site.env) stays
# a bash file shared by both shells. It also loads the completions of the geth command.

set -l geth_home (builtin realpath (status dirname))
set -l records (bash $geth_home/geth/bin/env_export.sh $geth_home/env.sh | string split0)
if test $pipestatus[1] -ne 0
    return 1
end

set -l i 1
while test $i -le (count $records)
    switch $records[$i]
        case set
            set -l name $records[(math $i + 1)]
            set -l value $records[(math $i + 2)]
            if string match -q -- '*PATH' $name
                set -gx $name (string split -- : $value)  # fish keeps PATH-like variables as lists
            else
                set -gx $name $value
            end
            set i (math $i + 3)
        case unset
            set -e -g $records[(math $i + 1)]
            set i (math $i + 2)
        case '*'
            echo "Geth: unexpected output from env_export.sh" >&2
            return 1
    end
end

source $geth_home/geth/completions/geth.fish
