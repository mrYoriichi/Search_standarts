"""Client app version and build variant.

APP_VERSION goes into `X-App-Version` on license-server requests; the
server answers 426 Upgrade Required when it is older than
MIN_SUPPORTED_VERSION.

For a new release: update here (duplicate the version in installer.iss),
check PUBLIC_BUILD, then build the installer. See BUILD.md.
"""

APP_VERSION = "0.5.1"

# One codebase — two builds (decision 2026-07-15, NOT a fork).
# True  — public build: license verify is fail-open. An unreachable
#         license server NEVER blocks the app (see compute_effective_status);
#         only explicit server answers block — revocation and 426.
# False — pilot build: offline longer than the grace period (1 day) blocks.
PUBLIC_BUILD = True
