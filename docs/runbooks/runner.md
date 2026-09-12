# Runner execution or history cleanup failure

Gitea availability does not prove a runner can execute work. Check runner unit,
readiness, queue age and the correlated canary run in `infrabox-monitor/canary`.
A capacity-one runner may legitimately be busy. Do not dispatch overlapping
canaries or declare an idle runner dead because it has no user jobs.

Canary jobs have a one-minute execution limit and publish no artifacts. The
monitor removes only completed runs in its own repository, keeping at most 12
and expiring those older than one hour. A retention failure is a warning; inspect
the monitoring identity's repository permissions and retry the scheduled sweep.
Never run cleanup against another repository or remove active user work.

Repair through the runner/Gitea owning roles. Preserve its isolated network,
mapped host UID and absence of runtime sockets. A successful correlated canary
plus new readiness observations verifies recovery; future trusted Platform
execution requires its own checks and must not reuse generic runner credentials.
