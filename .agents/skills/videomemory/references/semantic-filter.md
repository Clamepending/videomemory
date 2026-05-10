# Semantic Filter

The semantic filter gates frames before VLM analysis.

Recommended defaults:

- backend: `dino_clip_adapter`
- threshold: `0.3`
- threshold mode: `absolute`
- reduce: `max`
- smoothing: `0.0`
- ensemble: `off`

Use lower thresholds when the object is small or partly occluded. Use higher thresholds when false positives are expensive.

For event monitors, keywords should describe visible objects/classes, not the full action policy:

```text
good: phone, smartphone, hand, person
bad: tell me when the user holds the phone up and then notify me
```

The task description should still contain the full visual trigger condition.
