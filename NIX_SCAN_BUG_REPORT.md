# [RESOLVED] Nix packages never complete sync — fail at "Scanning Package" with no reason given

## Resolution (2026-08-20)

**Root cause:** an expired AWS STS session token used to sign pre-signed S3
uploads for this sandbox's `cloudsmith-package-uploads-dev-kharrison`
bucket. Every file upload attempt — for *any* package, not just `nix` —
was failing at the S3 layer with `ExpiredToken` / "The provided token has
expired." A server reset on the sandbox refreshed the token, and a repeat
push completed a full sync:

```json
"stage_str": "Fully Synchronised",
"status_str": "Completed",
"is_sync_completed": true,
"name": "xgcc",
"version": "15.2.0-libgcc",
"store_path": "/nix/store/vayna03pzyn98nlz8y4xcb1nncggb4nz-xgcc-15.2.0-libgcc"
```

This explains everything below without needing a nix-specific backend fix:
- The "Scanning Package" failures were a **downstream symptom**, not the
  root cause — the scan stage was choking on packages whose files never
  actually landed in S3 intact (the upload itself silently failed, but
  package-create still succeeded since it only needs an upload
  *identifier*, not confirmation the bytes arrived).
- A previously-unseen stage, **"Enriching Package"**, appears between
  `Queued` and the scan/completion stages once uploads actually succeed —
  this is what parses `.narinfo` content and populates `name`, `version`,
  `store_path`, `fully_qualified_name` (all `null` in every failed attempt
  above). So the original hypothesis that narinfo drives package metadata
  was correct in spirit, even though it wasn't the cause of the failures
  reported here.
- `security_scan_status` now resolves cleanly to `"Security Scanning Not
  Supported"` (a real terminal state) instead of hanging at `"Awaiting
  Security Scan"` — consistent with `is_security_scannable: false` being
  intentional for `nix`, not a bug.

**A real, separate CLI bug was found and fixed while debugging this:**
`upload_file()`/`multi_part_upload_file()` in
`cloudsmith_cli/core/api/files.py` raised `ApiException(status, headers=...,
body=...)` for a failed pre-signed upload **without a `detail=` kwarg**, so
`ApiException.__str__` fell back to the generic HTTP status phrase (e.g.
"Bad Request") and the CLI never showed the real reason — the `ExpiredToken`
message above only surfaced by manually reproducing the S3 request in
Python and reading the raw XML body. Fixed by extracting the `<Message>`
text from S3's XML error body (via a small regex, not a full XML parser —
this is response content from wherever `upload_url` points, so parsing it
with a real XML parser would add an XXE/entity-expansion attack surface for
no benefit over just pulling out one text field) and passing it through as
`ApiException.detail`. See `_s3_error_detail()` in
`cloudsmith_cli/core/api/files.py` and its tests in
`cloudsmith_cli/core/tests/test_files.py`. Future upload failures — token
expiry, bucket policy issues, whatever else — will now show their real
reason instead of a bare status phrase.

**No nix-specific code change was needed or made** for the original
"Scanning Package" failure — it was pure sandbox infrastructure. The
investigation below is preserved as-is for context.

**Update (2026-08-20, later the same day):** a distinct, more serious bug
was found reproducing on staging and production (not this sandbox) — nix
packages loop indefinitely rather than reaching a terminal state, with the
`.narinfo` file's checksum never getting computed server-side. See
[`NIX_NARINFO_CHECKSUM_SYNC_LOOP.md`](./NIX_NARINFO_CHECKSUM_SYNC_LOOP.md).
That issue is unrelated to the expired-token cause resolved here — it does
not reproduce on this sandbox at all.

---

## Summary

Every `nix` package pushed to a repository fails to synchronise. The package
is created successfully and its file(s) upload successfully, but the
package's sync pipeline dies at the **"Scanning Package"** stage
(`stage=4`) with `status="Failed"` and **`status_reason: null`** — no
diagnostic is surfaced anywhere in the API response. This reproduces
consistently (2/2 attempts), with or without the optional `narinfo` sidecar
file attached, and is not a timing/flake issue — both failed within 10–15
seconds of upload.

This blocks `nix` package support end-to-end: packages are visible in the
repo's package list, but are stuck in a failed, incomplete state
indefinitely (not downloadable, not synchronised) with no path to
resolution short of manual intervention.

## Environment

- **Instance:** `kharrison.cloudsmith.sh` (personal sandbox)
- **Organization/repo:** `cloudsmith/test-nix-support`
- **API version:** `cloudsmith-api` 2.0.30 (first release exposing
  `NixPackageUploadRequest` / `NixUpstream*` models)
- **Client:** `cloudsmith-cli` branch `kyleharrison/eng-12409/implement-nix-support`
  (commit `bf51ff3`), which adds `nix` to the CLI's supported push/upstream
  formats — see [cloudsmith-cli#365](https://github.com/cloudsmith-io/cloudsmith-cli/pull/365)
- **Auth:** authenticated as `lskillen` (Lee Skillen) via sandbox routing
  headers (`X-Region`, `X-Internal-User-Api-Key`)

> **Update (cloudsmith-api 2.0.31):** the SDK's `narinfo` field was renamed
> to `narinfo_file` (CLI flag is now `--narinfo-file`), and the CLI's
> separate special-casing for the old name was dropped since it now matches
> the generic `_file`-suffix upload convention natively. That resolved a
> distinct CLI-side 422 (see "Why this isn't a CLI bug" below) but is
> unrelated to the "Scanning Package" failure this report is about — the
> commands below use the flag name current at the time of this report
> (`--narinfo`); substitute `--narinfo-file` if reproducing against
> 2.0.31+.

## Steps to reproduce

```bash
# 1. Push a nix package (.nar.xz) with its narinfo sidecar
cloudsmith push nix -W cloudsmith/test-nix-support \
  1asxnrnab7w7jz7ilcbnvn2m3m85c3sx9847ap9hyc9n4jsds04x.nar.xz \
  --narinfo vayna03pzyn98nlz8y4xcb1nncggb4nz.narinfo

# -> Package created OK: slug 1asxnrnab7w7jz7ilcbnvn2m3m85c3sx9847ap9hyc9n4-wr4r
#    (slug_perm 685zgiIVJkip)

# 2. Poll status
cloudsmith status cloudsmith/test-nix-support/685zgiIVJkip -F json
```

Repeated without `--narinfo` (package-file only) for comparison:

```bash
cloudsmith push nix -W cloudsmith/test-nix-support \
  1asxnrnab7w7jz7ilcbnvn2m3m85c3sx9847ap9hyc9n4jsds04x.nar.xz

# -> Package created OK: slug 1asxnrnab7w7jz7ilcbnvn2m3m85c3sx9847ap9hyc9n4-iz3r
#    (slug_perm wSHjxbhNfjjs)
```

Both were also cross-checked via `cloudsmith list packages cloudsmith/test-nix-support -F json`.

## Expected result

The package's sync pipeline completes (`is_sync_completed: true`), or, if it
genuinely cannot be scanned/synced, fails with a populated `status_reason`
explaining why.

## Actual result

Both packages permanently show:

```json
"stage": 4,
"stage_str": "Scanning Package",
"status": 5,
"status_str": "Failed",
"status_reason": null,
"is_sync_completed": false,
"is_sync_failed": true,
"security_scan_status": "Awaiting Security Scan",
"is_security_scannable": false
```

Full package-list entries for both slugs (via `cloudsmith list packages`), trimmed to the relevant fields:

<details>
<summary>slug_perm 685zgiIVJkip (pushed with --narinfo)</summary>

```json
{
  "slug_perm": "685zgiIVJkip",
  "format": "nix",
  "files": [
    {
      "filename": "1asxnrnab7w7jz7ilcbnvn2m3m85c3sx9847ap9hyc9n4jsds04x.nar.xz",
      "tag": "pkg",
      "is_primary": true,
      "is_synchronised": true,
      "size": 54524
    },
    {
      "filename": "vayna03pzyn98nlz8y4xcb1nncggb4nz.narinfo",
      "tag": "narinfo",
      "is_primary": false,
      "is_synchronised": false,
      "size": 522
    }
  ],
  "num_files": 0,
  "is_downloadable": false,
  "is_security_scannable": false,
  "security_scan_status": "Awaiting Security Scan",
  "stage": 4,
  "stage_str": "Scanning Package",
  "status": 5,
  "status_str": "Failed",
  "status_reason": null,
  "sync_progress": 45,
  "uploaded_at": "2026-08-19T13:33:36.656111Z",
  "sync_finished_at": "2026-08-19T13:33:47.005853Z"
}
```
</details>

<details>
<summary>slug_perm wSHjxbhNfjjs (pushed without --narinfo)</summary>

```json
{
  "slug_perm": "wSHjxbhNfjjs",
  "format": "nix",
  "files": [
    {
      "filename": "1asxnrnab7w7jz7ilcbnvn2m3m85c3sx9847ap9hyc9n4jsds04x.nar.xz",
      "tag": "pkg",
      "is_primary": true,
      "is_synchronised": true,
      "size": 54524
    }
  ],
  "num_files": 0,
  "is_downloadable": false,
  "is_security_scannable": false,
  "security_scan_status": "Awaiting Security Scan",
  "stage": 4,
  "stage_str": "Scanning Package",
  "status": 5,
  "status_str": "Failed",
  "status_reason": null,
  "sync_progress": 45,
  "uploaded_at": "2026-08-19T13:36:03.758956Z",
  "sync_finished_at": "2026-08-19T13:36:10.386008Z"
}
```
</details>

## Notable inconsistency (possible root cause lead)

`is_security_scannable: false` on both packages, yet the sync pipeline still
enters (and fails at) a "Scanning Package" stage, while
`security_scan_status` stays at its initial `"Awaiting Security Scan"` and
never progresses. This looks like a **generic malware/content-scan stage
that runs unconditionally for every format**, separate from the
format-gated vulnerability scanner. If that generic scan stage doesn't have
a handler for `.nar.xz` / `.narinfo` content yet, it would plausibly error
out immediately rather than skip — which matches the fast, deterministic
`Failed` we observed (~10–15s, well before any real scan could run) and the
complete absence of a `status_reason`.

Also notable: on the package pushed with `--narinfo`, the primary `.nar.xz`
file reaches `is_synchronised: true`, but the `.narinfo` sidecar file stays
at `is_synchronised: false` — the package fails before ever finishing that
second file, regardless of it having uploaded correctly (checksums for both
files are present and correct in the response).

## Why this isn't a CLI bug

While investigating this, a real CLI bug was found and fixed separately
(`cloudsmith-cli` did not upload the `--narinfo` file via the file-upload
API before sending it to package-create, causing a 422 — fixed in
[#365](https://github.com/cloudsmith-io/cloudsmith-cli/pull/365)). After
that fix, `--narinfo` uploads correctly (see `is_synchronised: true` for the
primary file and a checksummed, attached `.narinfo` entry above) — but the
package still fails identically, **and pushing without `--narinfo` at all
fails the exact same way**. That rules the CLI out as the cause of the
scanning failure: the CLI is uploading files correctly and faithfully
surfacing every field the status API returns; there is no additional detail
being dropped client-side.

## Impact

- `nix` package support cannot ship — no package can reach a synchronised,
  downloadable state on this environment.
- No self-serve diagnosis is possible from the CLI/API side: `status_reason`
  is `null`, so whoever owns the scanning pipeline will need to check
  service-side logs for these package/repo identifiers around the given
  timestamps.

## Suggested next steps (superseded — see Resolution above)

These were written before the root cause was known; kept for context on
what was considered at the time.

1. ~~Check the package-scanning worker's logs...~~ — not needed once the
   expired token was identified as the actual cause.
2. ~~Confirm whether the generic "Scanning Package" stage has a content
   handler for the `nix` format yet...~~ — `is_security_scannable: false`
   for `nix` is confirmed intentional; it resolves cleanly to `"Security
   Scanning Not Supported"` once uploads actually succeed.
3. Still worth doing, independent of this report: consider whether
   `status_reason` should be populated for scan-stage failures in general,
   so a future upload-layer issue (expired token or otherwise) is
   diagnosable from `cloudsmith status` alone rather than requiring
   backend log access.
