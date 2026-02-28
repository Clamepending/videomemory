# VideoMemory Stream (Android)

Pushes your phone’s camera (and mic) to an RTMP server so VideoMemory can pull the feed via RTSP and run tasks on it.

## Requirements

- Android 7+ (API 24)
- Camera and microphone permissions
- Same LAN as the RTMP server (MediaMTX) and VideoMemory

## Build and run

1. Open the `android` folder in **Android Studio** (File → Open → select this folder).
2. Let Gradle sync (and download the RootEncoder dependency from JitPack if needed).
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

1. **Start MediaMTX** on your server/PC (see [rtmp-server/](../rtmp-server/README.md)).
2. In VideoMemory, go to **Devices** and click **Create RTMP camera** (optionally set a name like `front-door`).
3. Copy the generated URL and paste it into the Android app (example: `rtmp://192.168.1.42:1935/live/front-door`).
4. Tap **Start stream**. Grant camera and mic permissions if asked.
5. Create tasks for that device as usual. Stop the stream with **Stop stream** when done.

## Tech

- **RootEncoder** (pedroSG94): camera capture, H.264/AAC encode, RTMP push.
- Single screen: URL field, Start/Stop, camera preview.

## Play Store Readiness (Important)

This app is still a developer utility and needs release preparation before Play submission.

Current code improvements in this repo:
- `targetSdk` / `compileSdk` updated to Android 15 (API 35)
- foreground service notification while streaming (camera + microphone)
- basic runtime permission flow improvements

Before submitting to Google Play, complete the checklist in:

- `/Users/mark/Desktop/projects/videomemory/android/PLAY_STORE_CHECKLIST.md`
