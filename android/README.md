# VideoMemory Stream (Android)

Runs a tiny HTTP server on your phone that always returns the latest camera frame as a JPEG.

## Requirements

- Android 7+ (API 24)
- Camera permission
- Same LAN as the VideoMemory server, or Tailscale on both devices

## Build and run

1. Open the `android` folder in **Android Studio** (File → Open → select this folder).
2. Let Gradle sync.
3. Connect your phone via USB (or use an emulator); enable USB debugging.
4. Run the app (Run → Run 'app' or the green play button).

From the command line (with [Gradle installed](https://gradle.org/install/)):

```bash
cd android
gradle wrapper   # if gradlew is missing
./gradlew assembleDebug
# APK: app/build/outputs/apk/debug/app-debug.apk
```

## Usage

1. Start VideoMemory on your server or laptop.
2. Open the Android app and tap **Start Server**.
3. Copy the snapshot URL shown in the app.
4. In VideoMemory, go to **Devices** and add that URL as a network camera.
5. Create tasks for that device as usual. Stop the server from the app when you are done.

Your openclaw can guide and evendo steps 4 and 5 for you

## Tech

- **CameraX**: camera preview and frame capture.
- Tiny built-in HTTP server: serves `GET /snapshot.jpg` with the latest JPEG frame.
- Single screen: snapshot URL, Start/Stop, quality controls, camera preview.

## Play Store Readiness (Important)

This app is still a developer utility and needs release preparation before Play submission.

Current code improvements in this repo:
- `targetSdk` / `compileSdk` updated to Android 15 (API 35)
- direct snapshot server flow with no relay dependency
- basic runtime permission flow improvements

Before submitting to Google Play, complete the checklist in:

- `PLAY_STORE_CHECKLIST.md`
