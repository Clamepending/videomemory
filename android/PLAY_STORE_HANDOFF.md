# Play Store Release Handoff (VideoMemory Stream)

## Completed locally

- Bumped Android app version to `versionCode=2`, `versionName=1.0.1`.
- Added release signing config support in Gradle via `android/key.properties`.
- Generated upload keystore at `android/upload-keystore.jks`.
- Added `android/key.properties.example`.
- Added gitignore rules so signing secrets are not committed.
- Replaced placeholder system launcher icon usage with app launcher icon resources.
- Built signed release AAB:
  - `android/app/build/outputs/bundle/release/app-release.aab`

## Local files to keep safe

- `android/upload-keystore.jks`
- `android/key.properties`

If you lose this keystore, you will not be able to upload future updates with the same upload key.

## Remaining steps (manual / Play Console)

1. Create or open the app in Google Play Console.
2. Enable Play App Signing for the app (recommended).
3. Upload `app-release.aab` to Internal testing first.
4. Complete Store listing:
   - final app name
   - short description + full description
   - screenshots
   - feature graphic
   - high-res icon (512x512) for store listing
5. Complete App content forms:
   - privacy policy URL
   - data safety
   - camera/microphone permission declarations
   - content rating
   - target audience
6. Set pricing/distribution countries.
7. Start rollout (internal -> closed -> production).

## Recommended before production rollout

- Physical-device test pass on Android 13/14/15.
- Validate first-run permissions and denial flows.
- Validate start/stop behavior and recovery after app background/resume.
