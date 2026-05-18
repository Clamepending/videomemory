# VideoMemory Examples

## Voice Agent Demo

Path: `examples/voice-agent-demo`

A live browser voice/video agent that uses OpenAI Realtime for conversation and
VideoMemory for long-running camera monitors. It demonstrates:

- browser camera frames posted into VideoMemory,
- conversational tool calls that create monitors,
- VideoMemory webhook wakeups back into the voice agent,
- one-shot and persistent monitor lifecycles,
- a small apple-shopkeeper ledger demo,
- a fake camera for local testing.

Run it with:

```bash
cd examples/voice-agent-demo
OPENAI_API_KEY=sk-... npm start
```

See [voice-agent-demo/README.md](voice-agent-demo/README.md) for setup and tests.
