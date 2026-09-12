# InfraBox — OpenClaw Subnet Scanning

This incremental contract extends NetBox conversational onboarding with an
optional `infrabox_scan_subnet` tool. It supersedes the previous exclusions of
network scanning and custom OpenClaw plugins only for this bounded capability.
NetBox MCP, credentials, managed tags, and separate write confirmation retain
their existing contracts. Conversational acceptance remains operator-owned.

## Behavior and consent

- Accept one canonical IPv4 CIDR with prefix /24 through /32, at most 256
  addresses. Reject IPv6, hostnames, ranges, multiple targets, host bits, and
  arbitrary Nmap options. There is no address allowlist or private-only rule.
- Request native one-time approval before each scan, identifying the exact
  subnet. Explain active discovery probes, common TCP port checks, native OS
  fingerprinting, possible alerts or disturbance to fragile devices, and
  uncertain results. Approval confirms this is the user's own local network.
  Offer only allow-once or deny. Timeout and missing approval routing fail closed.
- Do not divide larger networks into smaller scans to bypass the limit. Every
  retry needs a fresh approval. NetBox writes need their own reviewed proposal
  and confirmation; scanning never writes inventory automatically.
- Return responsive IPv4 addresses, open ports from the fixed 28-port set, and
  up to five native Nmap OS matches per host with accuracy scores. Label matches
  as heuristic and missing matches as inconclusive. Scores are not calibrated
  probabilities. Do not infer hardware, identities, or platform relationships.
- A three-minute timeout stops the scan and reports incomplete results. Missing
  or filtered hosts and host timeouts never establish absence. The routed bridge
  can limit discovery, MAC visibility, and OS fingerprinting accuracy.

## Runtime

The managed native plugin uses OpenClaw 2026.9.4's
[plugin permission hook](https://docs.openclaw.ai/plugins/plugin-permission-requests)
and a private Unix socket to a separate Nmap worker. The Gateway remains UID
1000 without Linux capabilities, shell tools, or host runtime sockets. Its only
new mount is the read-only scanner socket directory; plugin code is image-owned.

The worker uses the existing digest-pinned Debian-based OpenClaw image for its
Python runtime and adds Nmap 7.93 plus exact checksum-locked Debian packages.
It builds without network access after verified package downloads. It has its
own automatically allocated Podman bridge, no published ports, no application
credentials, a read-only root filesystem, a 16 MiB temporary filesystem, 256 MiB
memory, one CPU, and 32 tasks. Only `CAP_NET_RAW` is retained for Nmap's native
TCP SYN and OS probes; host networking and privileged mode remain disabled.
The package lock currently supports x86_64 only.

Nmap receives fixed arguments: no reverse DNS, TCP SYN scan, native OS guesses
with one attempt and suitability filtering, one retry, 100 scan probes/second,
16-way scan parallelism, and a 20-second host timeout. The overall worker
deadline also bounds OS detection, which has its own probe behavior. No NSE,
service-version probes, arbitrary command arguments, or shell evaluation are
exposed. Refer to Nmap's [OS detection](https://nmap.org/book/man-os-detection.html)
and [performance controls](https://nmap.org/book/man-performance.html).

The tested TCP ports are 21, 22, 23, 25, 53, 80, 110, 111, 135, 139, 143,
389, 443, 445, 465, 587, 636, 993, 995, 1433, 2049, 3306, 3389, 5432,
5900, 8000, 8080, and 8443. Open ports are observations, not proof of a specific
application. Nmap may use other probe types for host and OS detection.

## Verification

Run local Python and Node tests covering validation, argument injection, busy
handling, deadlines, XML parsing, and the native approval request. Run Ansible
syntax checks and deploy with the authorized inventory. Check worker isolation,
version, Gateway socket access, invalid-target rejection, and plugin loading
without network scanning or model inference. Repeat deployment for idempotence.
Record actual runs in IMPLEMENTATION_STATUS. A live subnet scan and end-to-end
conversational approval remain operator checks, with explicit network approval.
