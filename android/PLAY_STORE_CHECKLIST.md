# Google Play Release Checklist (VideoMemory Stream Android App)

This app streams the device camera + microphone to a user-provided RTMP server.

## Code / App Behavior

- [ ] Confirm `targetSdkVersion` and `compileSdk` are current for Play policy (currently API 35 in this repo)
- [ ] Test on Android 13, 14, and 15 physical devices
- [ ] Verify foreground service notification appears while streaming
- [ ] Verify permission-denied behavior (camera/mic denied, notifications denied)
- [ ] Handle app backgrounding/rotation/resume scenarios cleanly
- [ ] Add connection retry / timeout UX (optional but recommended)

## Security / Privacy

- [ ] Publish a privacy policy URL (required for camera/microphone apps in most cases)
- [ ] Document what data is collected (ideally none by the app itself)
- [ ] Confirm app does not transmit data anywhere except the user-provided stream URL
- [ ] Complete Play Console Data safety form
- [ ] Complete Play Console Camera/Microphone permissions declarations

## Store Listing / Compliance

- [ ] App icon (replace Android system placeholder icon)
- [ ] Feature graphic + screenshots
- [ ] App description that clearly explains camera/mic streaming behavior
- [ ] Content rating questionnaire
- [ ] Country/region availability settings

## Release Build / Signing

- [ ] Create release keystore (or use existing org keystore)
- [ ] Enable Play App Signing (recommended)
- [ ] Build signed AAB (`bundleRelease`)
- [ ] Verify upload package installs and streams correctly

## Google Play Console Declarations (Likely)

- [ ] Camera permission usage
- [ ] Microphone permission usage
- [ ] Foreground service type declaration (camera/microphone)
- [ ] Data safety answers for transmission to user-configured servers

## Post-Release (Recommended)

- [ ] Crash reporting
- [ ] In-app error logging (sanitized)
- [ ] Simple diagnostics screen (encoder/network stats)
