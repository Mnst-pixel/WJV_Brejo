# Local LLM

The VPS has 4 CPU cores, 15 GiB RAM, no GPU, and substantial existing workload. The first runtime evaluation therefore targets CPU-only quantized models with strict memory and CPU limits. The supplied LocalAI source archive was verified and contains an MIT license; production uses a pinned official release rather than an unversioned master snapshot.

The benchmark evaluates at least three hardware-compatible candidates for Brazilian Portuguese, legal-domain caution, instruction following, tool calling, JSON output, citations, hallucination, context, latency, RAM, tokens per second, and stability. No model is selected solely by parameter count.

Until benchmark evidence is complete, the application treats AI as optional and displays `Consultor temporariamente indisponível` when necessary. No local runtime may induce host OOM or degrade pre-existing services.

