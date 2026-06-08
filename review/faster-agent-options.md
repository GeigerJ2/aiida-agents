# Making the agent faster: your GPU, and free cloud models

## Why it's slow now

`ollama ps` shows `qwen3.5:2b ... 100% CPU`. Your GPU is an **AMD Radeon RX 480**
(Polaris, gfx803, 2016), not NVIDIA, so CUDA / `nvidia-smi` never applied, and
Ollama is doing everything on the Ryzen CPU. A fast CPU is still slow for LLM token
generation.

## Option 1: use the RX 480 (Ollama's Vulkan backend, on Windows)

The catch: modern **ROCm dropped Polaris (gfx803)**, so the usual AMD-Ollama path
is out (you can sometimes force it with `HSA_OVERRIDE_GFX_VERSION`, but it's flaky
on Polaris because the ROCm libs lack the gfx803 code objects). The realistic path
is Ollama's **experimental Vulkan backend** (`OLLAMA_VULKAN=1`), which works on
Polaris and newer. The RX 480 has mature native Vulkan support on Windows, so your
instinct is right: run Ollama **natively on Windows** and avoid the WSL GPU layer.

1. Install Ollama for Windows.
2. Set Windows environment variables (System settings, or the shell that starts Ollama):
   - `OLLAMA_VULKAN=1`  (enable the Vulkan backend)
   - `OLLAMA_HOST=0.0.0.0`  (so WSL can reach it over the network)
3. Restart Ollama (quit from the tray, relaunch), then `ollama pull qwen3.5:2b`.
4. Confirm it's on the GPU: `ollama ps` on Windows should show a GPU processor,
   not `100% CPU`.

Point the WSL agent at the Windows Ollama:

- **Cleanest (Windows 11): mirrored networking.** In `%UserProfile%\.wslconfig`:
  ```
  [wsl2]
  networkingMode=mirrored
  ```
  then `wsl --shutdown` and reopen. Now `localhost:11434` from WSL reaches Windows
  Ollama, so the agent's default `OLLAMA_BASE_URL` just works, no override.
- **NAT mode (your current setup, gateway 172.24.0.1):** point at the host IP:
  ```bash
  export OLLAMA_BASE_URL="http://$(ip route show default | awk '{print $3}'):11434/v1"
  curl "$OLLAMA_BASE_URL/models"          # verify reachability first
  AIIDA_AGENT_MODEL=qwen3.5:2b uv run python -m aiida_agents.agent
  ```
  (The agent respects a pre-set `OLLAMA_BASE_URL`; its `setdefault` only fills it
  when unset.)

Reality check: the RX 480 (4-8 GB, 2016) over experimental Vulkan will beat 100%
CPU but won't feel like a modern GPU. Worth trying; temper expectations.

## Option 2: a free cloud model (fast, over the network)

You don't have to pay. OpenAI's own API is paid (no permanent free tier), but
several providers have **permanent free tiers** (rate-limited, email signup, no
credit card): Groq, OpenRouter (`:free` models), Google AI Studio (Gemini),
Cerebras, Mistral, Cohere, NVIDIA NIM.

**Easiest with the current code: Groq.** The current full `pydantic-ai` install
includes the Groq SDK, and `get_model`'s `else` branch routes through
`infer_model("groq:<model>")`:

```bash
# free key at console.groq.com/keys (email, no card)
AIIDA_AGENT_PROVIDER=groq \
GROQ_API_KEY=<your-key> \
AIIDA_AGENT_MODEL=<a current Groq model, see console.groq.com/docs/models> \
  uv run python -m aiida_agents.agent
```

(pydantic-ai's Groq provider reads `GROQ_API_KEY`.)

**After the proposed refactor** (bounded providers + `pydantic-ai-slim`), the Groq
SDK won't be installed, so reach Groq through its OpenAI-compatible endpoint
instead, which is exactly what the `openai-compatible` branch is for:

```bash
AIIDA_AGENT_PROVIDER=openai-compatible \
AIIDA_AGENT_BASE_URL=https://api.groq.com/openai/v1 \
AIIDA_AGENT_API_KEY=<your-key> \
AIIDA_AGENT_MODEL=<model> \
  uv run python -m aiida_agents.agent
```

Caveats: free tiers are rate-limited; and your prompts plus the tool results (pks,
labels, structures from your DB) leave your machine, which is precisely what
ADR-05's offline-first stance exists to avoid. Fine for trying it out, a real
consideration for the HPC target.

## Option 3: Ollama Cloud free tier (same tooling, cloud GPU)

Your Ollama account includes free cloud model usage, which skips the RX 480
entirely and reuses the exact Ollama API the agent already speaks. Free tier:
cloud model access, 1 concurrent model, "light usage" with session limits that
reset every 5 hours and weekly limits every 7 days (exact numbers show in your
account). The full cloud-enabled list is at `ollama.com/search?c=cloud`.

It's OpenAI-compatible at `https://ollama.com/v1` with an **API key** (a Bearer
token from your account settings, not the `ollama signin` device key), and the
agent's Ollama provider already reads `OLLAMA_BASE_URL` + `OLLAMA_API_KEY`, so no
code change:

Cloud hosts only the large models (small local tags like `qwen3.5:9b` 404 on the
cloud endpoint), so list what your account can actually serve before picking one:

```bash
curl -s https://ollama.com/v1/models -H "Authorization: Bearer <your-key>" | jq '.data[].id'
```

Then run with one of those IDs:

```bash
OLLAMA_BASE_URL=https://ollama.com/v1 \
OLLAMA_API_KEY=<your-key> \
AIIDA_AGENT_MODEL=<a cloud model id from the list above> \
  uv run python -m aiida_agents.agent
```

Model choice matters for tool calling. Dogfooding `gpt-oss:20b` connected fine
(HTTP 200) but failed with `UnexpectedModelBehavior: Exceeded maximum output
retries`: its reasoning/harmony format doesn't produce tool calls pydantic-ai
accepts. Prefer a Qwen 3.5 or GLM cloud model (clean OpenAI-style tool calls) over
the `gpt-oss` family. If pydantic-ai's default `retries=1` is too stingy, bump it
on the `Agent`.

Caveats: same as any cloud, prompts + tool results leave the machine (offline-first
tension), and the free tier has the 5h / weekly caps.

## Bottom line

- Easiest free + fast: Ollama Cloud free tier (Option 3) with a Qwen 3.5 model,
  one env-var change, reuses your Ollama setup, no GPU faff. Use `qwen3.5:9b`, not
  `gpt-oss` (which fails tool calling here).
- Groq free tier (Option 2) is the alternative if you'd rather not use Ollama Cloud.
- For local/offline: Windows-native Ollama + `OLLAMA_VULKAN=1` is the only
  realistic GPU path for the RX 480, and it's a modest gain.
