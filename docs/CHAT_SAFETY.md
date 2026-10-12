# Local chat transport and persistence safety (experimental v0.6)

AthenZ's command-line and desktop chat send prompts only to an explicitly
configured HTTP loopback Ollama endpoint. HTTP proxies and redirects are
refused. Calls may use approved private context; no chat content is uploaded
by AthenZ to a cloud provider.

The shared Ollama client now reads **at most 2 MiB + 1 byte** from each
non-streaming JSON reply, rejects oversized or malformed envelopes, requires
nonempty string content limited to 128 Ki characters, and avoids echoing
raw HTTP error text into messages. These bounds protect AthenZ against
unexpected local service output; they do not guarantee a hard memory bound
on Ollama itself, and cannot terminate server-side inference on cancellation.

For its **default reviewed model routing**, command-line chat validates the
pinned model/consent before and *after* generating each answer. A tag change,
revoked source approval, or a new routing selection during a slow generation
causes that reply to be discarded without recording it. `--model` is still an
explicit owner override of the default model route and does not carry the
reviewed-candidate guarantees.

Command-line chat writes the user message and matching assistant reply in one
SQLite transaction. If a write fails, both messages roll back. The reply is
shown only after that complete transaction succeeds, and SQLite error details
are not shown in the terminal. This prevents orphaned user messages after a
failed assistant insert, but is not a guarantee of crash-proof hardware or
filesystem operation. The desktop has its own separate cancellation gate and
transactional persistence.

These controls have synthetic and loopback-transport regression tests. They
have **not** been verified on the owner's physical Windows machine with the
RTX 3060, actual Ollama model, WSL2 Docker, or long-running inference.
