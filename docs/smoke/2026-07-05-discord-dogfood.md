# Discord Dogfood Smoke - 2026-07-05

This note records one end-to-end Discord bridge run against a small Home Assistant setup. It is meant as practical setup evidence, not a product claim.

## Environment

- Commit: `9d6bc4d`
- Runtime: Docker Compose on a HarborOS `.82` dogfood host
- Parser: `rules-only`
- Home Assistant snapshot: 23 entities
- Write mode: `false`
- Result: dry-run only; no Home Assistant files were changed

The host could not reach Docker Hub during rebuild. For this run, the bridge image was rebuilt from the already-present local image with the updated `/app/src`. This is not the recommended install path; it was only used to keep the private dogfood service on the latest code while the registry was unavailable.

## Smoke Messages

```text
devices
find camera
Tell me if the front door camera goes offline
Turn on the hallway light when someone arrives home
1
Run the evening scene when I say movie time
2
cancel
```

## Observed Result

- `devices` listed 23 Home Assistant entities.
- `find camera` correctly reported no matching camera entity.
- `front door camera` did not produce a guessed rule; the bot said it could not see that camera in the snapshot.
- `hallway light` did not get silently mapped to a different light; the bot explained that there was no exact match and offered `HarborDock Test Light` as a candidate.
- Replying with `1` updated the same draft into a readable `light.turn_on` rule.
- `evening scene` did not get silently mapped to a different scene; the bot offered the available HarborDock scenes.
- Replying with `2` updated the same draft into a readable `scene.turn_on` rule.
- `cancel` canceled the current draft.

## Notes

- The bot replied once per message; no duplicate bot instance was observed.
- The Discord gateway stayed connected during the run.
- The result stayed within the intended safe path: readable draft, explicit user action, dry-run by default.
