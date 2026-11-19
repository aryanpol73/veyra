"""Check every configured LLM endpoint with one tiny request each.

    python -m app.llm_check          (from backend/; in Docker: docker exec veyra python -m app.llm_check)
"""
from __future__ import annotations

import sys
import time

from app import llm_pool as pool

HINT = {
    "groq": "GROQ_API_KEY (console.groq.com/keys)",
    "mistral": "MISTRAL_API_KEY (console.mistral.ai, free Experiment plan)",
    "gemini": "GEMINI_API_KEY (aistudio.google.com/apikey)",
    "openrouter": "OPENROUTER_API_KEY (openrouter.ai/keys)",
    "ollama_cloud": "OLLAMA_API_KEY (needs paid credits)",
    "ollama_local": "OLLAMA_LOCAL=true with `ollama serve` running",
}


def main() -> int:
    seen, ok_any = set(), False
    for role in ("strong", "fast"):
        eps = pool.chain(role)
        print(f"\n{role} chain ({len(eps)} endpoint(s)):")
        if not eps:
            print("  none configured")
        for ep in eps:
            if ep.name in seen:
                print(f"  {ep.name:45s} (checked above)")
                continue
            seen.add(ep.name)
            t0 = time.perf_counter()
            try:
                r = pool.client_for(ep).chat.completions.create(
                    model=ep.model, messages=[{"role": "user", "content": "Reply with: ok"}], max_tokens=200)
                print(f"  OK    {ep.name:45s} {time.perf_counter() - t0:4.1f}s")
                ok_any = True
            except Exception as e:  # noqa: BLE001
                print(f"  FAIL  {ep.name:45s} {type(e).__name__}: {str(e)[:110]}")
    missing = [f"  {HINT[p]}" for p in pool.PROVIDERS if not pool.provider_key(p)]
    if missing:
        print("\nAdd more free capacity by setting any of:\n" + "\n".join(missing))
    return 0 if ok_any else 1


if __name__ == "__main__":
    sys.exit(main())
