# Migrations and advanced correction

Read alongside [inventory.md](inventory.md) before proposing an identity/type
change or removal of placeholders/superseded objects. The proposal must include
exact source and target objects, relationship transfers, losses and cascades.
An initial request to migrate or delete is not confirmation of that proposal.

Correct inaccurate inventory instead of preserving known placeholders forever.
For `infrabox-unknown`, propose creating/reusing the actual observed interface,
transferring IP assignments and primary relationships, then removing the obsolete
placeholder if approved. If a Device is actually a VM, inspect its full relevant
relationships and existing possible VM matches, propose the replacement and all
transfers/deletions, create/reuse and verify the VM, then delete the superseded
Device. Never claim relationships were transferred when the target model cannot
represent them; resolve those explicitly before removal. Preserve site, tags,
operator context and applicable relationships; the new NetBox ID is the identity
for future runs, while the original artifact retains its original Device ID.

Apply only the confirmed proposal: re-read current state, create/reuse the
replacement, transfer supported relationships, read back and verify them, then
delete the superseded object. If dependencies, cascades or unsupported
relationships differ from the proposal, stop and obtain confirmation of a revised
proposal before removal. On partial failure report completed and remaining work;
read current state before any retry, without blind creates/deletes or rollback.
For shared tag deletion, inspect all associations and distinguish deleting the
tag object from removing one association. Absence from incomplete results is
never a reason to remove or deactivate existing records.
