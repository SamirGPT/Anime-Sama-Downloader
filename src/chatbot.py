"""Chatbot powered by Groq (Qwen3) — natural language control of the downloader.

v4.1.1: Replaced the `groq` SDK with direct HTTP calls via `requests`.
This removes the `groq` dependency entirely — only `requests` (already
used everywhere else) is needed.

Uses Groq's function-calling to let the LLM trigger real actions:
search, download, list episodes, show config, etc.

API: https://api.groq.com/openai/v1/chat/completions (OpenAI-compatible)

Setup:
  export GROQ_API_KEY="gsk_..."   # required
  # or put it in the config via: python3 main.py chat --setup
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Optional, Any

import requests

from src import __version__
from src.config import get_config
from src.ui import Colors, print_separator, print_status, prompt
from .chatbot_tools import TOOLS_SCHEMA, execute_tool


# Default model — Qwen3 32B
DEFAULT_MODEL = "qwen/qwen3-32b"
# Fallback models if the primary is unavailable
FALLBACK_MODELS = [
    "qwen/qwen3-32b",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_TIMEOUT = 60  # seconds


SYSTEM_PROMPT = """Tu es l'assistant intégré d'Anime-Sama Downloader v{version}, un outil CLI pour télécharger des animes et scans depuis anime-sama.to et voiranime.rip.

Tu parles FRANÇAIS par défaut. Tu es cordial, efficace et direct.

CAPACITÉS:
- Rechercher des animes par nom (search_anime)
- Télécharger des épisodes (download) — épisodes: 'latest', 'all', '1', '1-10', '1,3,5'
- Lister les épisodes d'un anime (list_episodes)
- Afficher l'historique (show_history) et les stats (show_stats)
- Afficher/modifier la config (show_config, update_config)
- Diagnostiquer l'installation (show_doctor)
- Lister les sites supportés (list_sites)
- Mettre à jour le programme (self_update)
- Donner la version (get_version) et l'aide (get_help)

RÈGLES:
1. Si l'utilisateur te donne une URL complète, utilise-la directement avec download ou list_episodes.
2. Si l'utilisateur te donne juste un nom d'anime, fais d'abord un search_anime, montre les résultats, et demande-lui de confirmer (ou prends le 1er si évident).
3. Pour le téléchargement, demande toujours confirmation avant si ce n'est pas évident (ex: "all" épisodes d'une longue série).
4. Si une action échoue, explique pourquoi et propose une solution.
5. Réponds concisément — pas de blabla inutile, l'utilisateur veut de l'efficacité.
6. N'invente jamais d'URLs. Si tu n'as pas l'URL, fais une recherche d'abord.

SITE PAR DÉFAUT: anime-sama.to (domaine .to, pas .eu ni .fr)
""".format(version=__version__)


def _get_api_key() -> Optional[str]:
    """Get the Groq API key from env or config."""
    key = os.environ.get("GROQ_API_KEY")
    if key:
        return key
    cfg = get_config()
    return getattr(cfg, "groq_api_key", None) or None


def _call_groq(api_key: str, messages: List[Dict], model: str,
               tools: List[Dict]) -> Dict:
    """Call the Groq API directly via requests. Returns the parsed JSON response.

    Raises requests.RequestException on network error, ValueError on API error.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0.6,
        "max_tokens": 2048,
    }

    resp = requests.post(
        GROQ_API_URL,
        headers=headers,
        json=payload,
        timeout=GROQ_TIMEOUT,
    )

    if resp.status_code == 404:
        # Model not found — raise a specific error so we can fallback
        raise ValueError(f"Model {model} not found (404)")
    if resp.status_code == 401:
        raise ValueError("Clé API Groq invalide (401)")
    if resp.status_code == 429:
        raise ValueError("Rate limit Groq atteint (429) — réessaie dans quelques secondes")
    if resp.status_code >= 400:
        try:
            err_data = resp.json()
            err_msg = err_data.get("error", {}).get("message", resp.text)
        except Exception:
            err_msg = resp.text
        raise ValueError(f"Erreur API Groq ({resp.status_code}): {err_msg}")

    return resp.json()


def _get_response(api_key: str, messages: List[Dict]) -> Dict:
    """Try models in order until one works. Returns the response dict."""
    last_error = None
    for model in FALLBACK_MODELS:
        try:
            return _call_groq(api_key, messages, model, TOOLS_SCHEMA)
        except ValueError as e:
            err_str = str(e).lower()
            if "404" in err_str or "not found" in err_str or "model" in err_str:
                # Try next model
                last_error = e
                continue
            # Real error (auth, rate limit) — don't try other models
            raise
        except requests.RequestException as e:
            raise ValueError(f"Erreur réseau: {e}")
    raise ValueError(f"Aucun modèle Groq disponible. Dernière erreur: {last_error}")


def chat_loop(api_key: Optional[str] = None, one_shot: Optional[str] = None) -> int:
    """Main chat loop. If one_shot is given, execute it and exit.

    Returns exit code (0 = success, 1 = error).
    """
    api_key = api_key or _get_api_key()
    if not api_key:
        print_status(
            "Clé API Groq manquante.\n"
            "Obtiens une clé gratuite sur https://console.groq.com/keys\n"
            "Puis: export GROQ_API_KEY='gsk_...'\n"
            "Ou: python3 main.py chat --setup",
            "error",
        )
        return 1

    print(f"\n{Colors.BOLD}{Colors.HEADER}🤖 CHATBOT ANIME-SAMA — v{__version__}{Colors.ENDC}")
    print_separator()
    print(f"{Colors.OKCYAN}Modèle: Qwen3-32B via Groq LPU{Colors.ENDC}")
    print(f"{Colors.OKCYAN}Tape 'quit' / 'exit' / Ctrl+C pour quitter{Colors.ENDC}")
    print(f"{Colors.OKCYAN}Tape 'help' pour l'aide{Colors.ENDC}")
    print_separator()

    # Conversation history
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]

    # One-shot mode
    if one_shot:
        print(f"\n{Colors.BOLD}Toi:{Colors.ENDC} {one_shot}")
        messages.append({"role": "user", "content": one_shot})
        return _process_turn(api_key, messages, interactive=False)

    # Interactive loop
    while True:
        try:
            user_input = prompt("\nToi: ")
        except (EOFError, KeyboardInterrupt):
            print(f"\n{Colors.OKCYAN}Au revoir! 👋{Colors.ENDC}")
            return 0
        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q", ":q"):
            print(f"{Colors.OKCYAN}Au revoir! 👋{Colors.ENDC}")
            return 0
        if user_input.lower() in ("help", "?", "aide"):
            print(execute_tool("get_help", {}))
            continue

        messages.append({"role": "user", "content": user_input})
        _process_turn(api_key, messages, interactive=True)


def _process_turn(api_key: str, messages: List[Dict], interactive: bool) -> int:
    """Process one conversation turn: get LLM response, execute tools, reply."""
    # Cap history to last 20 messages to avoid token bloat
    if len(messages) > 22:
        # Keep system + last 20
        messages[:] = [messages[0]] + messages[-20:]

    try:
        response = _get_response(api_key, messages)
    except ValueError as e:
        print_status(str(e), "error")
        return 1
    except Exception as e:
        print_status(f"Erreur inattendue: {e}", "error")
        return 1

    # Parse the response
    choices = response.get("choices", [])
    if not choices:
        print_status("Réponse vide de l'API", "error")
        return 1

    msg = choices[0].get("message", {})

    # Handle tool calls (may loop multiple times if LLM chains calls)
    max_iterations = 5
    for _ in range(max_iterations):
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            break

        # Execute each tool call
        for tool_call in tool_calls:
            fn = tool_call.get("function", {})
            name = fn.get("name", "")
            args_str = fn.get("arguments", "{}")
            try:
                args = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError:
                args = {}

            print_status(f"🔧 Exécute: {name}({args})", "info")
            result = execute_tool(name, args)
            # Truncate very long results
            if len(result) > 3000:
                result = result[:3000] + "\n... [tronqué]"
            print_status(f"→ {result[:200]}{'...' if len(result) > 200 else ''}", "info")

            # Append tool result to messages (OpenAI format)
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tool_call.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": args_str or "{}",
                        },
                    }
                ],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.get("id", ""),
                "content": result,
            })

        # Get next response (may have more tool calls or final text)
        try:
            response = _get_response(api_key, messages)
        except ValueError as e:
            print_status(f"Erreur API suite: {e}", "error")
            return 1
        choices = response.get("choices", [])
        if not choices:
            break
        msg = choices[0].get("message", {})

    # Final text response
    final_text = msg.get("content") or "(pas de réponse texte)"
    print(f"\n{Colors.BOLD}{Colors.OKGREEN}Bot:{Colors.ENDC} {final_text}")
    messages.append({"role": "assistant", "content": final_text})
    return 0


def setup_api_key() -> int:
    """Interactive setup: prompt for API key and save to config."""
    print(f"\n{Colors.BOLD}{Colors.HEADER}🔑 Configuration de la clé API Groq{Colors.ENDC}")
    print_separator()
    print("1. Va sur https://console.groq.com/keys")
    print("2. Crée un compte (gratuit) si besoin")
    print("3. Crée une nouvelle API key")
    print("4. Copie-la ci-dessous:")
    print_separator()
    try:
        key = prompt("Ta clé (gsk_...): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAnnulé.")
        return 1
    if not key or not key.startswith("gsk_"):
        print_status("Clé invalide — doit commencer par 'gsk_'", "error")
        return 1

    # Save to config file directly
    cfg = get_config()
    cfg.update(groq_api_key=key)

    print_status("Clé API sauvegardée dans la config!", "success")
    print_status("Tu peux maintenant lancer: python3 main.py chat", "info")
    return 0
