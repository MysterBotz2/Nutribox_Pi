# PI-2B device pairing

PI-2B identifies a Nutri-Box Pi with the backend; it does not delegate a user’s
authorization. Meal analysis stays anonymous and the device token is only used
for `GET /api/device/me`.

The Pi starts pairing with `POST /api/device-pairing/start` and exactly
`{"device_name":"NutriBox Pi"}`. It keeps session id, six-digit code, token,
and UTC expiry only in memory, displays only the code and safe expiry, and polls
`POST /api/device-pairing/status` every three seconds. Status is exactly
`pending`, `expired`, or `paired`. After `paired`, it verifies
`GET /api/device/me` with `X-Device-Token`, and persists only after success.

On Linux the credential is atomically stored at
`$XDG_CONFIG_HOME/nutribox-pi/device-token.json` (or
`~/.config/nutribox-pi/device-token.json`), with a 0700 directory and 0600
file. Symlink targets are rejected. No session id, code, user JWT, account id,
or backend secret is persisted. A startup 401 removes the local credential.

Production requires HTTPS; local HTTP is development-only. Missing server-side
pairing-code attempt/rate limits are a production blocker the Pi cannot solve.
Swagger may temporarily act as the authenticated mobile claimant; do not retain
tokens, codes, or logs in validation evidence.
