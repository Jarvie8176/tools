"""llm-pipeline-monitor — independent live dashboard for a local LLM inference pipeline.

A Prometheus *consumer* (distinct from cc-monitor, which produces Claude-Code-session metrics):
queries the isolated ``llm_endpoint_*`` / ``llm_host_*`` series from an upstream Prometheus and
renders per-endpoint state — resident model (served gguf, drift-proof), throughput (tok/s), host
GPU/VRAM, per-session context usage, and model-swap events — over an SSE-driven SPA.

Reuses the cc-monitor operational shell (stdlib server, SSE broker, config plane, single-file SPA
serving, systemd/tailnet-edge deploy) with its own data plane. Designed to extend across the wider
pipeline (gateway spend, digest) as further Prometheus-fed legs land.
"""

__version__ = "0.1.0"
