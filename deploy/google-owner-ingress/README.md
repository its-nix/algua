# Public owner dashboard: Google only

Prepared configuration, **not an installed deployment**. Canonical origin:
`https://algua.itsnix.cloud`; `https://itsnix.cloud` is the VPS web front door and
redirects there for now. No Telegram integration. Existing dashboard Web Push remains the
notification channel. Google login grants dashboard access only; it grants no trading authority.

## Boundary and prerequisites

Dedicated nginx workers (`algua-ingress`) bind **72.61.190.172:443 only** and authenticate every
application route through OAuth2 Proxy's Google provider. Only the single email in a private,
root-controlled allowlist can sign in. Verified email replaces `Tailscale-User-Login` on the
private backend connection; inbound identity and authorization headers are discarded. The
backend remains on its Unix socket, with no TCP listener. Auth has its own private systemd
socket, reachable only by ingress/root. A new `algua-web-edge` group permits ingress to traverse
the backend socket directory; it must contain no agent/operator/other-app users.

The shared nginx (`www-data`) keeps port 80 and its existing sites. Its only addition is the
two named hosts' ACME challenge/HTTPS redirect server. Tailscale's address-bound HTTPS listeners
and the other application on 8321 must remain unchanged. Do not add wildcard public 443,
IPv6 listeners, public backend ports, a proxy in shared www-data, or agent group membership.
Root and the dashboard UID remain trusted, as in the existing installation.

Before cutover record `ss -lntp`, `nginx -T`, `tailscale serve status`, unit/drop-in contents,
socket permissions, current group memberships and authoritative DNS. Back up root-owned config
outside the repository. Verify the observed listeners still match the preceding assumptions;
stop if any service already owns public `72.61.190.172:443`. This is dashboard ingress work,
not acceptance of unattended live trading or trust-anchor deployment hardening.

## Owner provisioning (required before activation)

### Recover an expired cached dashboard

`https://algua.itsnix.cloud/api/auth/recover` serves a fixed public recovery document, with no
application data. It is an exact GET/HEAD exception; all private API, asset and PWA routes remain
authenticated. Its button removes only this origin's root-scope worker and root Workbox precache,
then opens the fixed Google sign-in path. Query parameters cannot choose a redirect. The user may
need to enable alerts again after this one-time repair. Normal session recovery preserves the
worker and push subscription.

This path is needed for clients with the old worker: it cached OAuth navigation and could not
download its protected replacement after the session expired. Keep the inline-script hash in
`auth-recovery.conf` synchronized with the HTML; the focused CSP test checks the exact bytes.

### OAuth client and DNS

1. In Hostinger DNS replace/create **only** these website A records (TTL 300 during cutover):

   | Name | Type | Value |
   | --- | --- | --- |
   | `@` | A | `72.61.190.172` |
   | `algua` | A | `72.61.190.172` |

   The observed old apex address was `2.57.91.91`; verify it before replacing. Preserve MX,
   TXT/SPF/DKIM/DMARC and all other apps' records. Resolve conflicting CNAMEs and stale AAAA
   records for these two website names only; no IPv6 service is configured here. Verify public
   authoritative answers and any CAA policy before requesting certificates.
2. In the owner's Google Cloud project configure Google Auth Platform branding/audience for
   this personal app. Create an OAuth client of type **Web application** with origin
   `https://algua.itsnix.cloud` and exact authorized redirect URI
   **`https://algua.itsnix.cloud/oauth2/callback`**. If the audience is in Testing, enroll only
   the owner as a test user and account for Google's test-mode/session restrictions. No domain
   delegation, service account, Gmail/Drive permissions, domain-wide allowlist or second provider.
3. Deliver client ID and client secret directly into the private VPS config below. Never paste
   them, cookies or the owner's email into commits, logs, shell history, tickets or screenshots.
   The owner email must equal the existing private `ALGUA_WEB_OWNER_LOGIN` exactly.

## Install reviewed templates (root, on the VPS)

Use the reviewed source directory as `deploy/google-owner-ingress` below. Existing web build,
data paths and VAPID state/contact stay in place. First install distro nginx with
`http_auth_request_module`, CA roots and certbot using the host's package manager. Check
`nginx -V` includes auth-request. Never replace the shared nginx config wholesale.

```sh
useradd --system --no-create-home --shell /usr/sbin/nologin algua-ingress
useradd --system --no-create-home --shell /usr/sbin/nologin algua-auth
groupadd --system algua-web-edge
usermod -a -G algua-web-edge algua-ingress
install -d -o root -g root -m 0755 /etc/algua-ingress
install -d -o root -g algua-auth -m 0750 /etc/algua-google-auth
install -d -o root -g root -m 0755 /usr/local/lib/algua-google-auth /var/lib/algua-acme
install -o root -g root -m 0644 deploy/google-owner-ingress/nginx.conf deploy/google-owner-ingress/oauth-headers.conf deploy/google-owner-ingress/dashboard.conf deploy/google-owner-ingress/auth-recovery.conf deploy/google-owner-ingress/auth-recovery.html /etc/algua-ingress/
install -o root -g algua-auth -m 0640 deploy/google-owner-ingress/oauth2-proxy.cfg /etc/algua-google-auth/
install -o root -g algua-auth -m 0640 /dev/null /etc/algua-google-auth/owner-email
install -o root -g root -m 0600 /dev/null /etc/algua-google-auth/secrets.env
```

Skip user/group creation if already present, after inspecting its identity and memberships.
Use a private root editor to fill `owner-email` with exactly one owner Google email, one line,
and `secrets.env` with these keys (systemd reads the root-only file before dropping UID):

```text
OAUTH2_PROXY_CLIENT_ID=<Google client ID>
OAUTH2_PROXY_CLIENT_SECRET=<Google client secret>
OAUTH2_PROXY_COOKIE_SECRET=<base64url encoding of 32 random bytes>
```

Generate the random cookie secret directly to a private file/editor; do not print it in a
shared terminal transcript. Do not add `OAUTH2_PROXY_EMAIL_DOMAINS` or other environment overrides.
Inspect the existing web unit's `EnvironmentFile` paths and confirm the owner setting matches.

Pin OAuth2 Proxy **v7.15.6** (official latest release checked 2026-11-15). For the observed
amd64 VPS, download the official release archive and verify its SHA-256 before extraction:

```sh
install -d -m 0700 /root/algua-auth-install
cd /root/algua-auth-install
curl -fLO https://github.com/oauth2-proxy/oauth2-proxy/releases/download/v7.15.6/oauth2-proxy-v7.15.6.linux-amd64.tar.gz
printf '%s  %s\n' 91b3e86d9c2de679a516e6696704e3fd1acf67e8b8f7be77b618f086f72fb1f0 oauth2-proxy-v7.15.6.linux-amd64.tar.gz | sha256sum -c -
tar -xzf oauth2-proxy-v7.15.6.linux-amd64.tar.gz
install -o root -g root -m 0755 oauth2-proxy-v7.15.6.linux-amd64/oauth2-proxy /usr/local/lib/algua-google-auth/oauth2-proxy
/usr/local/lib/algua-google-auth/oauth2-proxy --version
```

Return to the reviewed source root before the remaining copy commands. Confirm machine
architecture with `uname -m`; a different architecture needs its corresponding official asset
and independently verified checksum. Binary and configs must be root-owned and runtime users
must not be able to change any parent directory.

Install the HTTP fragment into the shared nginx include directory (Debian/Ubuntu example
`/etc/nginx/sites-available/algua-public`, symlink into `sites-enabled`). Check for duplicate
`server_name` blocks first; merge only those hosts if necessary. Run `nginx -t` then reload
**nginx.service**. After DNS resolves and HTTP challenge files are reachable, issue both SANs:

```sh
certbot certonly --webroot -w /var/lib/algua-acme -d algua.itsnix.cloud -d itsnix.cloud
install -d -m 0755 /etc/systemd/system/algua-web.service.d
install -o root -g root -m 0644 deploy/google-owner-ingress/web-public.conf /etc/systemd/system/algua-web.service.d/public-ingress.conf
install -o root -g root -m 0644 deploy/google-owner-ingress/algua-ingress.service deploy/google-owner-ingress/algua-google-auth.service deploy/google-owner-ingress/algua-google-auth.socket /etc/systemd/system/
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/algua-ingress.service /etc/systemd/system/algua-google-auth.service /etc/systemd/system/algua-google-auth.socket
systemctl restart algua-web
```

Before starting ingress verify `namei -l /run/algua-web/web.sock` shows a directory owned by
`algua-web:algua-web-edge` with mode `0710`. Uvicorn's `0666` socket is safe only behind that
directory. Confirm `algua-web` retains the original `algua-web` supplementary group and data
access. Confirm actual agent UIDs cannot connect to either socket; do not broaden permissions
to fix a denial. `algua-ingress` must connect to the backend and must not read OAuth secrets.
Confirm `algua-auth` cannot traverse the backend socket directory or read the registry,
broker configuration or `/etc/algua/web.env`; it needs only its OAuth config, system CA roots
and outbound HTTPS/DNS. Check these permissions as the actual service users with `sudo -u`
and connection attempts, including the deployed `algua` agent UID. A failed expectation blocks
activation. Keep the new group membership limited to the two dedicated web/ingress identities
(the web service uses it as its primary group through the drop-in).

```sh
nginx -t -c /etc/algua-ingress/nginx.conf
systemctl enable --now algua-google-auth.socket algua-ingress.service
```

The auth service starts on socket demand. Inspect both units' status/journal without exposing
secrets. Arrange a root-owned certbot deploy hook to run
`/usr/sbin/nginx -t -c /etc/algua-ingress/nginx.conf` followed, only on success, by
`systemctl reload algua-ingress.service`; verify renewal with `certbot renew --dry-run`.
Keep existing shared nginx/Tailscale renewal hooks. Restrict firewall exposure to the intended
HTTP/HTTPS listeners; preserve SSH, Tailscale and other apps' current rules.

## Acceptance before declaring cutover complete

Use `curl --resolve algua.itsnix.cloud:443:72.61.190.172` to test before local DNS catches up.
Do not use `-k` for acceptance. Repeat with normal public DNS from a non-tailnet connection.

- No cookie: `/` and a deep link go to Google sign-in; `/api/fleet`, `/api/inbox`,
  `/api/push/key`, `/healthz`, `/sw.js`, `/manifest.webmanifest`, and `/assets/test.js`
  return 401, never dashboard bytes. POST `/api/inbox` and `/api/push/subscribe` refuse too.
  `/share` may initiate login but must never create an Inbox item while unauthenticated.
- Repeat with forged `Tailscale-User-Login`, `X-Auth-Request-Email`, `X-Forwarded-Email`,
  `Authorization`, `X-Forwarded-Host` and `X-Forwarded-Proto` headers: same refusal.
- Log in with a second Google account absent from the file: forbidden, no application/API
  access or write. Log in with owner: home, deep links, APIs, built assets, manifest and service
  worker load; same-origin Inbox/share and push subscription work. Cross-site writes still
  fail the application's existing guard. Verify a real dashboard push reaches the device.
- Expire/clear cookies: APIs and service-worker update checks refuse; open the dashboard in
  the browser to sign in again. Sessions intentionally expire after one hour; no silent
  refresh-cookie propagation is needed. Restart auth and confirm valid sessions behave as
  expected; rotate cookie secret to revoke all sessions immediately. Removing owner and
  restarting auth must block subsequent owner requests, including existing cookies.
- Check public raw IP/unknown Host does not serve the app, HTTP redirects stay on the canonical
  domain, and both certificate names validate. Both root-domain and existing other-app sites
  must still work. Compare listener inventory and Tailscale access with the saved baseline.
- Check `systemctl restart` and a host reboot recreate both sockets with the same permissions
  and services recover. Auth stopped/unavailable must give 5xx/401, never bypass auth.

PWA installation, service workers, cookies and push subscriptions are **origin-specific**.
Sign in on the new origin before installing its PWA; enable alerts there to create a new push
subscription. Keep existing VAPID keys/state. Old Tailscale installations/subscriptions do not
migrate automatically; revoke old subscriptions through existing UI if duplicated. Existing
installed clients may retain cached shell files after logout; this ingress is not a remote
device cache wipe. Protected live API calls still require the Google session. Share Target
POSTs after session expiry cannot be replayed by OAuth: sign in, then share again and confirm
one item. Do not exempt `/share`, push endpoints, PWA files or `/healthz` to make this work.

Existing Tailscale access can remain as the private recovery path with its existing identity
boundary. Public traffic uses Google only; it does not fall back to Tailscale identity.

## Rollback

Stop/disable `algua-ingress.service` and `algua-google-auth.socket` (also stop the auth service),
restore the previous web drop-in and restart `algua-web` to recover the original `0700` socket
directory. Remove only the new HTTP fragment and test/reload shared nginx. Restore saved DNS
website records if required, accounting for TTL. Verify the original Tailscale dashboard and
other apps. Preserve web/VAPID/database state and the existing Tailscale serve configuration.

## Official references

- [OAuth2 Proxy v7.15.6 release and assets](https://github.com/oauth2-proxy/oauth2-proxy/releases/tag/v7.15.6)
- [Google provider](https://oauth2-proxy.github.io/oauth2-proxy/configuration/providers/google/)
- [Configuration options](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview/)
- [Systemd socket activation](https://oauth2-proxy.github.io/oauth2-proxy/configuration/systemd_socket/)
- [nginx auth_request](https://nginx.org/en/docs/http/ngx_http_auth_request_module.html)
- [Google web OAuth client and redirect requirements](https://developers.google.com/identity/protocols/oauth2/web-server)
