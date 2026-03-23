# Google Play Release Checklist (VideoMemory Stream Android App)

This app exposes the device camera through a simple HTTP snapshot endpoint for a user-controlled VideoMemory instance.

## Code / App Behavior

- [ ] Confirm `targetSdkVersion` and `compileSdk` are current for Play policy (currently API 35 in this repo)
- [ ] Test on Android 13, 14, and 15 physical devices
- [ ] Verify permission-denied behavior (camera denied, notifications denied)
- [ ] Handle app backgrounding/rotation/resume scenarios cleanly
- [ ] Add connection retry / timeout UX (optional but recommended)

## Security / Privacy

- [ ] Publish a privacy policy URL (required for camera apps in most cases)
- [ ] Document what data is collected (ideally none by the app itself)
- [ ] Confirm app does not transmit data anywhere except the user-controlled snapshot session
- [ ] Complete Play Console Data safety form
- [ ] Complete Play Console Camera permissions declarations

## Store Listing / Compliance

- [ ] App icon (replace Android system placeholder icon)
- [ ] Feature graphic + screenshots
- [ ] App description that clearly explains direct snapshot serving behavior
- [ ] Content rating questionnaire
- [ ] Country/region availability settings

## Release Build / Signing

- [ ] Create release keystore (or use existing org keystore)
- [ ] Enable Play App Signing (recommended)
- [ ] Build signed AAB (`bundleRelease`)
- [ ] Verify upload package installs and serves snapshots correctly

## Google Play Console Declarations (Likely)

- [ ] Camera permission usage
- [ ] Data safety answers for transmission to user-controlled servers

## Post-Release (Recommended)

- [ ] Crash reporting
- [ ] In-app error logging (sanitized)
- [ ] Simple diagnostics screen (encoder/network stats)
