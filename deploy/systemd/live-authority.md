# Installed live authority — draft, not deployment approval

The live artifact and the development checkout are builds of the same application. Source
`uv run algua ...` retains development enrollment and explicit synthetic anchor paths. Keep all
development/research processes credential-free and without live service-control access. The live
build replaces `signer_anchor.py` with the reviewed installed policy; both alternative policy
modules, cached bytecode, source enrollment and git objects are absent. There is no runtime mode
switch. A source checkout or development build is never an accepted live runtime.

`deploy/scripts/build-live-artifact.py` builds from an exact commit, reusing the existing paper
builder only to materialize locked dependencies. It emits a distinct live descriptor and blocked
acceptance status; a paper descriptor/adoption receipt grants no live authority. `--development`
selects a different artifact during assembly, never during live execution. Review its inventory,
the policy hashes in both source and installed package, the commit-substituted live entry and all
external runtime dependencies before installation. Do not run the paper adoption helper on it.
The recipe is unprivileged preparation only; no merge, root install, credential provisioning or
service activation follows from it.

The installed policy only accepts `/etc/algua/authority/allowed_signers`. Each full signature
verification opens `/`, `etc`, `algua`, `authority` and both files descriptor-relatively, without
symlinks. Directories must be root-owned and not group/other writable; files must be regular,
root-owned and exactly 0644. Extended POSIX ACLs refuse. Empty/oversized content, malformed or
extra/duplicate manifest fields and digest mismatch refuse. `installed.json` has exactly:

```json
{"schema":"algua-authority/v1","allowed_signers_sha256":"64 lowercase hex SHA-256 characters"}
```

Copy the existing human-reviewed public enrollment bytes unchanged. The manifest binds those
bytes; it does not approve a strategy, modify a payload, enroll a key or replace the live ceremony.
The loader copies validated content into a sealed Linux memfd. Namespace checks and both absolute
`/usr/bin/ssh-keygen` calls use the same bytes and inherited `/proc/self/fd/N` descriptor. Missing
sealing/proc-FD support refuses; no temporary-file fallback exists in the live artifact. The
separate development loader uses a private temporary snapshot for platform compatibility.

All existing strict/capped/frozen, live risk configuration/restoration, doctor, watcher and exit
consumers converge at `live_gate.verify_signature`. Installed enrollment refuses. Paper actions
stay unsigned. Existing full verification remains at invocation entry; cheap mid-order revocation
hooks do not promise immediate signer removal during a tick. A failed anchor does not authorize
an unsigned exit, flatten an account or cancel existing venue exposure.

## Installation acceptance remains blocked

The entry template is commit-substituted by assembly and must be installed physically as
`/usr/local/libexec/algua-live-entry` by the human. It uses the exact release under
`/opt/algua/releases/<commit>`, isolated Python `-I -S`, explicit installed site-packages and no
`.pth` execution. The policy itself checks isolated startup, physical release/import paths,
root ownership, modes, ACLs and symlinks, so bypassing the wrapper does not select development
policy. Absolute OpenSSH and interpreter paths are checked too. Nonroot execution,
NoNewPrivileges and zero effective/permitted/inheritable/ambient capabilities are mandatory.
Installed transitions and `operator lock-run` share the fixed
`/var/lib/algua-live/operator.lock`; source/paper retain their existing Git-directory locks.
The supplied system units additionally deny namespace creation and runtime writes outside the
live state directory. They are definitions only, without timers or installation commands.

These source checks are not deployment acceptance. The interpreter executes before Python can
inspect itself; its ELF loader/shared libraries, stdlib/native extension dependencies, system
OpenSSH dependencies, entry and service manager/configuration must all be reviewed, inventoried
and runtime-unwritable. The existing materializer records an external Python and explicitly does
not produce a self-contained runtime. This draft does not certify that external closure. Installed CLI imports also reach vectorbt/Numba,
which needs a usable cache locator for a nonroot process. The isolated test uses a disposable cache;
no production cache policy is supplied or certified here. Resolve its generated executable/cache
trust and prewarming requirements without changing trading numerics before installation. Prove
mount/namespace restrictions on the intended host, including overlays; no runtime capability,
user namespace or service-control route may replace trusted paths. A container source test is
not that proof. Validate runtime checks against the target layout; conservative symlink/ACL
refusals can intentionally reject an otherwise ordinary Python installation.

Use a dedicated `algua-live` UID with no shared agent/research process, sudo, release/enrollment
or service-write access. Only the separately authorized trusted supervisor receives live
credentials. A wrapper is not protection from a hostile credential-bearing same-UID shell.
Unreviewed strategy Python cannot run there; existing process-group containment is not a strategy
sandbox. The existing reviewed-code residual boundary remains an acceptance decision. The unit
files do not resolve it. Independently test serialization/recovery between live ticks and the
risk watcher before considering either unit for installation.

## Maintenance, outage and recovery

After separate human approval, stop/drain services under an approved maintenance procedure,
record pending orders/reconciliation state, and install anchor plus matching manifest with
separate atomic replacements. Their pair is not online atomic: an intermediate mismatch safely
refuses. Existing signatures retain their payloads, nonces and restrictions; nothing consumes a
challenge or mints an approval during installation. Check the actual runtime UID cannot overwrite,
unlink/rename or substitute any authority, entry, release, interpreter or import ancestor. Record
digests and permission evidence without secrets before separately authorizing activation.

Approve an outage procedure covering alerts, exposure monitoring and separately authorized manual
broker intervention. Authority failure can block already-authorized risk reductions/exits; stopping
a service does not remove market exposure. Recovery restores previously reviewed public bytes
and matching manifest plus a compatible reviewed immutable runtime while services remain stopped.
Retain financial/registry history and reconcile uncertain venue state before separately approved
resume. No fallback to source keys, relaxed checks or stage flags is permitted. Authority is not
part of automatic paper rollback. Restoring revoked keys requires human review; trusted root can
restore an old matching pair, so no anti-root or monotonic rollback guarantee is claimed.
