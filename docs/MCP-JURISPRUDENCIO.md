# MCP Jurisprudêncio

Supplied archive SHA-256: `9ea64f8a04a511ebf569e07ab8c6cee8bcb8202d1fb54f854a1c58d743618800`  
Observed entries: 26  
Components: TypeScript/Fastify gateway, Node ESM MCP server, and Python FastMCP container.

The included runbook targets another environment and is explicitly rejected for Kairós. Paths under `/var/www/jurisprudencio`, the existing `mcp-brasil` container, host Redis, PM2, host Nginx, and any existing gateway are out of scope.

Kairós uses private DNS names on `kairos-mcp`, independently generated bearer/API keys, restricted CORS, no secret URL by default, rate limits, timeouts, output caps, and redacted logs. INLABS remains disabled until its credentials are provided. A current official DataJud credential must be validated before declaring DataJud operational.

The supplied source declares no license file or package license field. Its exact source is therefore kept out of the public repository pending rights confirmation; the adapted integration and provenance manifest are versioned separately.

