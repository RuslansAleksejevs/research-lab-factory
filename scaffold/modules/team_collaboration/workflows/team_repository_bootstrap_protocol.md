# Team repository bootstrap protocol

Repository setup is independent from laboratory generation. Generation never
initializes Git, contacts GitHub, or stores credentials.

## Dry-run plan

The steward supplies the exact repository name, visibility, Git author identity,
default branch, and GitHub handles. `plan` inventories and hashes the exact
baseline files, writes an immutable local plan, and prints its SHA-256. It runs
neither `git` nor `gh`.

`UNDECIDED` visibility cannot be applied. Choose `LOCAL_ONLY`, `PRIVATE`, or
`PUBLIC` explicitly for the plan. Private/public plans require all configured
members to have GitHub handles matching the exact inputs.

## Public disclosure gate

For `PUBLIC`, copy the disclosure-review template into
`collaboration/repository/reviews/`, bind it to the plan SHA-256, and have every
member approve all checks. Review source rights, secrets, personal data, and
research exposure. The apply command rejects drift in the planned inventory.

## Explicit apply

Apply requires the steward, the root-relative plan path, its exact SHA-256, and
the `apply` subcommand. Only then may the script initialize Git. Remote plans
use the locally installed authenticated `gh` CLI to create one repository and
invite the exact declared collaborators. The script never accepts or records a
token.

Every attempt writes an append-only receipt. A partial external failure is not
rolled back destructively: the receipt and Control Room summary report `ERROR`,
and the team inspects real Git/GitHub state before preparing a new plan.

