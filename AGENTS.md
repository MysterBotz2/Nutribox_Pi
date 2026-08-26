# Repository guidance

- Treat `docs/PI0_SCOPE.md` as the binding scope for PI-0.
- Keep the Raspberry Pi client online-only during PI-0.
- Never send a trusted `user_id` from this device.
- Do not invent recognition-confidence fields or requirements.
- Do not add camera, touchscreen UI, GPIO, real sensors, heating, profiles,
  pairing, authentication, synchronization, telemetry, or persistence without a
  later approved phase and its safety/API requirements.
- Keep hardware and network access behind ports so adapters remain replaceable.
- Run `pytest`, `ruff check .`, and `git diff --check` before handoff when the
  relevant tools and Git metadata are available.

PI-2B permits limited device pairing only. Never store a user JWT or use a
device token for meal analysis or other user-owned actions.
