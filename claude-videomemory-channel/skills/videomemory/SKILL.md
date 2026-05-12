---
name: videomemory
description: Use when the user asks Claude to install, download, set up, or use VideoMemory to watch a camera for a visual condition.
---

# VideoMemory

VideoMemory is a local camera monitor for Claude Code. Treat it as the user's
local perception service: VideoMemory owns the video stream and long-running
watch loop; Claude owns the user request and the follow-up response.

When the user says something like "download VideoMemory and watch my dog from my
FaceTime camera":

1. Call `mcp__videomemory__setup_local` first.
   - Use the default `camera_id: "facetime"` unless the user names another
     camera.
   - This starts/checks the local VideoMemory service, wires the webhook back to
     this Claude channel, and opens the browser FaceTime camera bridge.
2. If setup returns `readiness.ready: false`, report the exact readiness
   warnings and tell the user to grant browser camera permission in the opened
   camera tab. Do not claim the monitor is armed yet.
3. Use `mcp__videomemory__list_devices` only if the user names a different
   camera or setup did not identify the expected device.
4. Create the monitor with `mcp__videomemory__create_monitor`.
   - Put only the visual condition in `task_description`, for example
     `the user's pet dog is visible`.
   - Use `io_id: "browser_facetime"` for the browser FaceTime bridge unless the
     user chose a different device.
   - Use `monitor_type: "binary"` for simple true/false criteria such as "dog
     is visible", "person is at the door", or "phone is held up".
   - Use `monitor_type: "general"` only when the user wants richer notes or
     open-ended scene analysis.
5. Read the create-monitor response. If `readiness.ready` is false, surface the
   blocker. If ready, tell the user the monitor is armed and VideoMemory will
   wake Claude when the condition is met.
6. Do not poll. VideoMemory will push a channel event when the monitor fires.

For incoming VideoMemory channel events, use the event note/task fields to
decide the response. If a test asks for a visible reply, call
`mcp__videomemory__reply`.
