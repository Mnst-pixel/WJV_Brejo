# Local LLM

The VPS has 4 CPU cores, 15 GiB RAM, no GPU, and substantial existing workload. The first runtime evaluation therefore targets CPU-only quantized models with strict memory and CPU limits. The supplied LocalAI source archive was verified and contains an MIT license; production uses a pinned official release rather than an unversioned master snapshot.

The benchmark evaluates at least three hardware-compatible candidates for Brazilian Portuguese, legal-domain caution, instruction following, tool calling, JSON output, citations, hallucination, context, latency, RAM, tokens per second, and stability. No model is selected solely by parameter count.

Until benchmark evidence is complete, the application treats AI as optional and displays `Consultor temporariamente indisponível` when necessary. No local runtime may induce host OOM or degrade pre-existing services.

## Deployed verification — 2026-08-28

- LocalAI is pinned to `v4.9.0`. Its CPU `llama-cpp` backend was installed from the official backend gallery and resolved to image digest `sha256:80697ab5b004b4246f2337289e4797e48053a834d10d7df1dedd9299536485f3`. Backend metadata is persisted below `/srv/kairos/localai-backends`.
- The pinned Qwen3 1.7B and multilingual-e5-small GGUF files passed their repository size and SHA-256 gates. The private embeddings endpoint returned 384 dimensions, and the private chat endpoint returned HTTP 200 without exposing either service to the host.
- Qwen3 1.7B has a 32,768-token native context window; production deliberately limits it to 8,192 tokens to protect this CPU-only VPS and its pre-existing workloads.
- Hermes Agent `v2026.8.19` enforces a 64,000-token minimum for custom providers. That is incompatible with the selected hardware-safe model. Kairós therefore keeps the legal assistant in its documented fail-open unavailable state instead of falsifying model capacity, patching upstream at runtime, or risking host pressure with an 8B-class replacement.
- The RAG policy remains fail-closed: with no human-approved legal corpus, consultations return evidence insufficiency, zero confidence, and no citations without calling a model.
