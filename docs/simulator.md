# Simulator

A separate FastAPI process that speaks Ollama's HTTP API. Tests and demos point the service at it in place of a real Ollama. It always gives the same answer to the same call, so tests can expect exact results, and it can be told to fail the way a real model server does.

## Running it

- It runs as its own process on `SIM_PORT` (11435 by default), and keeps its faults in memory. Restarting the simulator clears them; restarting the API or the worker does not.
- In `pnpm dev` it starts before the service. If it is down, the service's calls fail as `ProviderUnavailable`.
- Because faults outlive a service restart, a test clears them through `/_sim/faults`, or restarts the simulator, before it starts.

## Switching to and from Ollama

- The service has two provider profiles, each with a base URL, a processing model and a judge model:

  | Profile | Base URL | Processing model | Judge model |
  |---|---|---|---|
  | `simulator` | `http://localhost:11435` | `fake` | `fake-judge` |
  | `ollama` | `http://localhost:11434` | `qwen3:0.6b` | `qwen3:8b` |

  These are defaults; [Processing NFR-5](specs/processing.md#nfr-5-models) and [Prompt Improvement NFR-2](specs/prompt-improvement.md#nfr-2-judge-model) own them.
- The service starts on `simulator`. `PUT /_provider` switches profiles; the choice is kept in memory only.
- Both profiles go through the same Ollama adapter. The different model names keep the breakers apart.

## How it answers

- **Intent:** it looks for an intent's name in the message, ignoring case and reading `_` as a space: "I have a problem with billing" is `billing`, "a technical issue at login" is `technical_issue`. If several appear, the first wins. An intent counts only if the prompt names it; otherwise, or with no intent in the message, the answer is `other`.
- **Urgency:** `high` if the message contains "urgent" or "asap", otherwise `normal`. The judge uses the same rule, so urgency is never in error.
- **Seeded prompt:** it names `billing`, `shipping`, and `technical_issue`, but not `cancellation` or `account`, so those messages come back as `other` until a review adds them.
- **Judge:** it recognises every intent, whatever the prompt names. Its proposal appends to the base prompt the name of each intent among the errors it was shown.
- **Like Ollama:** it reports token counts, and answers 404 for a model it doesn't know.

## Faults

A fault is set on the simulator's `/_sim/faults` endpoints or in its startup config. It applies to every answer given from when it is set until it is cleared through `/_sim/faults`, so it also hits a call that is still being delayed, and to every model or just one (`fake` or `fake-judge`).

- **Order:** when several faults match a call, the one set first wins. A delay is the exception: the call waits, then any other matching fault decides its answer.
- **Reach:** the API and the worker call the same simulator, so a fault reaches both.

| Fault | The call... |
|---|---|
| 5xx | answers with a server error |
| 429 | answers 429 with a given `Retry-After` |
| Reject | is refused as sent (another 4xx) |
| Never answer | gets no answer, so the service's attempt times out |
| Delay | answers after a given number of seconds |
| Malformed JSON | answers with output that isn't JSON |
| Schema violation | answers with JSON that doesn't match the call's schema |
| Truncated | answers with output cut off at the token limit (`done_reason: "length"`) |
| Harmful proposal | returns a proposal that names no intent: it drops every intent the base prompt names and adds none. Only proposal calls are affected |
