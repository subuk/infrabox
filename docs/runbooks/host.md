# Host resource, clock or storage failure

[Runbook index](../README.md#troubleshooting) · [Operations](../operations.md)

Check the affected filesystem's free bytes/inodes and mount source, available
memory, sustained CPU load, clock synchronization and read-only state. A missing
expected data mount must not be hidden by an empty directory on rootfs.

Use `findmnt`, `df`, `free`, `chronyc tracking` and selected systemd unit state.
Do not fill a real data disk to test alerts. For acceptance use synthetic rule
fixtures or bounded disposable storage. Do not delete application data as a
routine resource fix. Retention and capacity changes belong in owning roles.

Recover the intended mount/clock/resource state and require fresh observations.
Confirm service dependencies separately if resource pressure caused failures.
Host-down detection during total loss needs an observer outside this appliance.
