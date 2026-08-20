# Nix packages loop forever on staging/production: `.narinfo` file checksum never computed

## Summary

A `nix` package push (`.nar.xz` primary file + `.narinfo` sidecar via
`--narinfo-file`) succeeds — both files upload, the package is created, both
files are correctly attached with checksums computed *client-side* — but the
package **never reaches a terminal sync state** on `cloudsmith.io`
(production) or `api-stg.cloudsmith.io` (staging). It cycles indefinitely
through sync stages, occasionally landing on a transient `Failed` before
being auto-requeued back to `Queued`, forever. `status_reason` stays `null`
throughout, so there is no self-serve diagnosis available.

The same push, with the exact same two files, completes cleanly to `Fully
Synchronised` every time on a personal preview sandbox
(`kharrison.cloudsmith.sh`) — 3/3 clean runs. That environment split points
squarely at a backend difference in nix package ingestion, not the CLI, not
the input files, and not narinfo content.

## Environments

| Environment | Host | Result |
|---|---|---|
| Personal sandbox | `kharrison.cloudsmith.sh` | ✅ 3/3 clean, `Fully Synchronised` |
| Staging | `api-stg.cloudsmith.io` | ❌ Loops indefinitely, never terminal |
| Production | `api.cloudsmith.io` | ❌ Looped indefinitely until manually deleted |

Client: `cloudsmith-cli` branch `kyleharrison/eng-12409/implement-nix-support`,
`cloudsmith-api` 2.0.31 (`--narinfo-file`, post-#365/#369 fixes — see "Why
this isn't a CLI bug" below).

## The concrete, consistent lead: `.narinfo` file checksum is never populated

In every failing run, the primary `.nar.xz` file's checksum is correctly
recorded, but the `.narinfo` sidecar file's checksum stays `null` even
though it's flagged `is_synchronised: true`:

**Production** (`cloudsmith/nix-upstreams`, slug_perm `6GeDYe3c7Ogj`), from
the package-detail "delete" confirmation dump (captured directly from the
web UI while the package was still cycling):
```
Package file: slug_perm="3dBhoCWaxZA3", filename="1asxnrnab7w7jz7ilcbnvn2m3m85c3sx9847ap9hyc9n4jsds04x.nar.xz",
  checksum_sha256="9d00ddb42436310fd35587a0d4f56005d55185dd76311acf97879fa56cb65dab"
Package file: slug_perm="X2rsV7XGxJqZ", filename="vayna03pzyn98nlz8y4xcb1nncggb4nz.narinfo",
  checksum_sha256="None"
```

**Staging** (`cloudsmith/testing-private`, slug_perm `0Zw8QNuCv0dr`), via
`cloudsmith list packages -q format:nix`:
```
1asxnrnab7w7jz7ilcbnvn2m3m85c3sx9847ap9hyc9n4jsds04x.nar.xz  checksum_sha256=9d00ddb4...  is_synchronised=True
vayna03pzyn98nlz8y4xcb1nncggb4nz.narinfo                     checksum_sha256=None       is_synchronised=True
```

**Sandbox control** (`cloudsmith/test-nix-support`, slug_perm
`Y3SexkLfLV3b`), same two source files, same command:
```
1asxnrnab7w7jz7ilcbnvn2m3m85c3sx9847ap9hyc9n4jsds04x.nar.xz  checksum_sha256=9d00ddb4...  is_synchronised=True
vayna03pzyn98nlz8y4xcb1nncggb4nz.narinfo                     checksum_sha256=b23c05f7...  is_synchronised=True
```

Same input files, same client, same command — the only variable is which
backend received the request.

## Behaviour observed while stuck

Polling `cloudsmith status` every 5–10s over several minutes on both
staging and production shows the package cycling through sync stages
without ever setting `ok` or `failed` to a stable `true`:

```
Queued → Retrieving Package File(s) → Enriching Package →
Parsing Package Metadata → Assembling/Verifying Package → Queued → ...
```

(Staging's cycle starts a stage earlier — `Adding Package to Repository` /
`Preparing for Synch` — before reaching the same later stages; likely just
queue-position noise on a busier shared environment, not a different bug.)

On production, the web UI showed `Status: Enriching Package [resync] 3` —
i.e. an internal resync mechanism had already retried 3 times on its own,
independent of the CLI's `--sync-attempts` (which governs the CLI's own
post-`failed` resync calls, not whatever is looping this server-side). On
staging, a `list packages` snapshot caught the package as `stage="Adding
Package to Repository", status="Failed"`, but a `status` call moments later
showed it back at `"Queued"` — confirming it isn't just slow, it's actively
being requeued from a terminal-looking `Failed` state.

**No self-remediation is possible while this is happening:** on production,
the package showed `is_deletable: false`, `is_resyncable: false`,
`is_cancellable: false` — all locked because `is_sync_in_flight: true`. The
only way to clear it was a manual deletion via the web UI's admin path,
which the account owner did directly (not via the CLI/API, which refused).

## Why this isn't a CLI bug

- Both files upload successfully and are correctly attached to the package
  (visible in `files[]` with correct sizes and, for `.nar.xz`, correct
  checksums) on every environment, including the two that loop.
- The narinfo-upload fix from
  [#365](https://github.com/cloudsmith-io/cloudsmith-cli/pull/365) and the
  `narinfo_file` rename (cloudsmith-api 2.0.31) are both confirmed working —
  this is a completely different failure surface than the earlier 422/400
  upload issues.
- The CLI is not asked to compute or transmit the `.narinfo` file's
  checksum as part of ingestion — that's a server-side computation during
  sync, and it's specifically that computation that's missing on
  staging/production but present on the sandbox.
- `status_reason` is `null` on every poll on every environment; the CLI is
  faithfully surfacing every field the API returns, there's nothing being
  dropped client-side.

## Ruled out: client-side timing, ordering, and content collisions

Given the divergence is so clean (sandbox always works, staging/production
never do), several client-controllable variables were tested directly
against the raw API (bypassing the CLI's own upload orchestration
entirely) to see if any of them mattered:

| Variable tested | Where | Result |
|---|---|---|
| Same content pushed into a second repo (content-addressable-storage collision theory) | Sandbox | ✅ Clean, both repos fully synchronised, both checksums populated |
| Upload order reversed (`.nar.xz` before `.narinfo`) | Sandbox | ✅ Clean |
| Both files uploaded concurrently (threads) | Sandbox | ✅ Clean |
| `packages_upload_nix` fired before the S3 uploads finished (race) | Sandbox | ✅ Clean |
| Guaranteed-fresh, 100%-synthetic content (no real-world collision possible), normal CLI, normal timing | Staging | ❌ Still loops, `.narinfo` checksum still `None` |

The synthetic-content test is the decisive one: a `.nar.xz`/`.narinfo` pair
generated from random bytes moments before the push (correct nix base32
`FileHash`/`NarHash`/`StorePath` — it parses and creates the package fine)
cannot possibly have existed anywhere on staging before this test, ruling
out "this exact content already exists from a real nixpkgs mirror or
another team's test" as an explanation. It looped identically to the real
`xgcc` package. **This is not a race condition and not a content
collision — it's an unconditional backend behavior difference between the
sandbox and staging/production.**

## Impact

- Any `nix` package push to production or staging today gets stuck
  indefinitely consuming worker/queue resources, with no terminal
  success or failure state and no diagnosable reason.
- No API-driven cleanup is available while a package is stuck — it must be
  removed out-of-band (as was done manually on production here).
- This blocks `nix` support from being usable on production entirely, not
  just as a rough edge — every push will hit this.

## Suggested next steps

1. Diff whatever handles nix package ingestion between the
   `kharrison.cloudsmith.sh` preview build and staging/production — the
   narinfo-checksum computation step is the concrete divergence point.
   Given the sandbox works and staging/production don't *unconditionally*
   (confirmed with fresh synthetic content, normal timing — see "Ruled
   out" above), this smells like a fix present on a feature branch/preview
   deploy that hasn't been promoted, rather than a fresh regression, a
   race, or a data-collision issue to hunt for from scratch.
2. Independent of the above: the "cycle back to `Queued` after transient
   `Failed`" behavior and the total lack of `status_reason` deserve a fix
   regardless of root cause — a stuck package should terminally fail with a
   reason, not loop forever consuming resources.
3. Consider whether `is_deletable`/`is_resyncable`/`is_cancellable` should
   allow intervention on a package that's been cycling for an abnormal
   length of time, since `is_sync_in_flight` currently blocks all
   self-service cleanup for exactly the packages that need it most.

## Related

See [`NIX_SCAN_BUG_REPORT.md`](./NIX_SCAN_BUG_REPORT.md) for an earlier,
now-resolved investigation on the sandbox (an expired S3 upload token,
unrelated to this) that surfaced the "Enriching Package" stage and
confirmed narinfo drives package metadata (`name`, `version`, `store_path`)
when ingestion succeeds.
