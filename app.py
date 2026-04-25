import json
import os
import re
import secrets
import shutil
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Deque, Dict, List, Optional, Tuple
from urllib import error, request

from flask import Flask, jsonify, render_template, request as flask_request

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
ENV_PATH = BASE_DIR / ".env"
CONFIG_LOCK = Lock()

AI_STATUS_LOCK = Lock()
LAST_AI_PROVIDER = ""
LAST_AI_ERROR = "not_attempted"
LAST_AI_ATTEMPT_AT = ""

CONVERSATION_LOCK = Lock()
CONVERSATIONS: Dict[str, Deque[Dict[str, str]]] = {}
MAX_CONVERSATION_TURNS = 14


def record_ai_status(provider: str, error_message: Optional[str] = None) -> None:
    global LAST_AI_PROVIDER, LAST_AI_ERROR, LAST_AI_ATTEMPT_AT
    with AI_STATUS_LOCK:
        LAST_AI_PROVIDER = provider
        LAST_AI_ATTEMPT_AT = datetime.now(timezone.utc).isoformat()
        LAST_AI_ERROR = error_message or ""


def format_provider_error(exc: Exception) -> str:
    if isinstance(exc, error.HTTPError):
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="ignore")[:220]
        except Exception:
            body = ""
        if body:
            return f"http_{exc.code}: {body}"
        return f"http_{exc.code}"
    return str(exc)[:220] or exc.__class__.__name__


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_config(config_path: Path) -> Dict[str, Any]:
    if not config_path.exists():
        return {}

    with config_path.open("r", encoding="utf-8") as file_obj:
        return json.load(file_obj)


def save_config(config_path: Path, data: Dict[str, Any]) -> None:
    backup_path = config_path.with_suffix(".backup.json")
    if config_path.exists():
        shutil.copyfile(config_path, backup_path)

    rendered = json.dumps(data, indent=2, ensure_ascii=False)
    config_path.write_text(rendered + "\n", encoding="utf-8")


def admin_enabled() -> bool:
    return bool(os.getenv("ADMIN_TOKEN", "").strip())


def admin_authorized() -> bool:
    expected = os.getenv("ADMIN_TOKEN", "").strip()
    supplied = (
        flask_request.headers.get("X-Admin-Token")
        or flask_request.args.get("token")
        or ""
    ).strip()
    return bool(expected and supplied and secrets.compare_digest(expected, supplied))


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def format_hours(hours_obj: Dict[str, str]) -> str:
    if not isinstance(hours_obj, dict) or not hours_obj:
        return "Hours are currently unavailable."

    ordered_days = [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]
    lines = []
    for day in ordered_days:
        value = hours_obj.get(day)
        if value:
            lines.append(f"- {day.title()}: {value}")

    return "Hours:\n" + "\n".join(lines)


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9']+", normalize_text(text))


def faq_match_details(message: str, faqs: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(faqs, list):
        return None

    message_tokens = set(tokenize(message))
    if not message_tokens:
        return None

    best_item: Optional[Dict[str, str]] = None
    best_score = 0.0
    best_overlap = 0

    for item in faqs:
        if not isinstance(item, dict):
            continue
        question = item.get("question", "")
        answer = item.get("answer", "")
        if not question or not answer:
            continue

        question_tokens = set(tokenize(question))
        if not question_tokens:
            continue

        overlap = len(message_tokens.intersection(question_tokens))
        coverage = overlap / max(1, len(question_tokens))
        precision = overlap / max(1, len(message_tokens))
        score = (coverage * 0.7) + (precision * 0.3)

        if score > best_score:
            best_score = score
            best_overlap = overlap
            best_item = item

    if not best_item:
        return None

    return {
        "item": best_item,
        "score": best_score,
        "overlap": best_overlap,
    }


def build_weekend_plan(config: Dict[str, Any]) -> str:
    brunch = config.get("brunch", {})
    happy_hour = config.get("happy_hour", {})
    menus = config.get("menus", {})

    brunch_details = brunch.get("details", "Weekend brunch is available.")
    hh_details = happy_hour.get("details", "Happy hour details are available on request.")
    dinner_menu_url = menus.get("main", {}).get("url", "")

    lines = [
        "Weekend itinerary suggestion:",
        "1) Late morning: Start with brunch and coffee.",
        f"   {brunch_details}",
        "2) Afternoon: Keep it light with starters or sandwiches.",
        "3) 4pm-6pm: Hit happy hour for drinks and bites.",
        f"   {hh_details}",
        "4) Evening: Choose mains and dessert for dinner.",
    ]

    if dinner_menu_url:
        lines.append(f"   Dinner menu: {dinner_menu_url}")

    return "\n".join(lines)


def build_event_roadmap(config: Dict[str, Any]) -> str:
    events = config.get("events", [])
    buzz = None
    for item in events if isinstance(events, list) else []:
        if isinstance(item, dict) and "buzz" in item.get("name", "").lower():
            buzz = item
            break

    details = buzz.get("details", "Plan around a 5pm-7pm event block with light bites.") if buzz else "Plan around a 5pm-7pm event block with light bites."
    contact = buzz.get("contact", "Contact the venue for scheduling and logistics.") if buzz else "Contact the venue for scheduling and logistics."

    return "\n".join(
        [
            "Event roadmap (step-by-step):",
            "1) Define event goal and target guest count.",
            "2) Lock date/time window and confirm room capacity.",
            f"3) Align food and drink package. {details}",
            "4) Assign hosts and guest check-in flow.",
            "5) Confirm budget and donation/activation mechanics if needed.",
            f"6) Finalize with venue contact. {contact}",
        ]
    )


def build_menu_comparison(config: Dict[str, Any]) -> str:
    menus = config.get("menus", {})
    main = menus.get("main", {})
    cocktails = menus.get("cocktails", {})
    kids = menus.get("kids", {})

    main_items = ", ".join((main.get("popular_items") or [])[:5])
    cocktail_items = ", ".join((cocktails.get("popular_items") or [])[:4])
    kids_items = ", ".join((kids.get("popular_items") or [])[:4])

    lines = [
        "Quick menu comparison:",
        f"- Lunch/Dinner focus: {main_items or 'Chef favorites and comfort classics.'}",
        f"- Cocktail focus: {cocktail_items or 'Signature cocktails and mocktails.'}",
        f"- Family/kids focus: {kids_items or 'Kid-friendly plates and simple sides.'}",
    ]

    if main.get("url"):
        lines.append(f"- Full lunch/dinner menu: {main['url']}")
    if cocktails.get("url"):
        lines.append(f"- Full cocktails menu: {cocktails['url']}")
    if kids.get("url"):
        lines.append(f"- Full kids menu: {kids['url']}")

    return "\n".join(lines)


def call_json_api(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: int = 25) -> Dict[str, Any]:
    merged_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "MITEX-Chatbot/1.0 (+local-dev)",
    }
    merged_headers.update(headers)

    req = request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers=merged_headers,
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def groq_chat(message: str, system_prompt: Optional[str] = None) -> Optional[str]:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        record_ai_status("groq", "missing_groq_api_key")
        return None

    model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system_prompt or "You are a concise helpful restaurant assistant.",
            },
            {"role": "user", "content": message},
        ],
        "temperature": 0.3,
    }

    try:
        data = call_json_api(
            url="https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            payload=payload,
        )
    except (error.URLError, error.HTTPError, TimeoutError, ValueError) as exc:
        record_ai_status("groq", f"request_failed: {format_provider_error(exc)}")
        return None

    choices = data.get("choices", [])
    if not choices:
        record_ai_status("groq", "no_choices_in_response")
        return None

    answer = choices[0].get("message", {}).get("content")
    if not answer:
        record_ai_status("groq", "empty_content")
        return None

    record_ai_status("groq")
    return answer


def openai_chat(message: str, system_prompt: Optional[str] = None) -> Optional[str]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        record_ai_status("openai", "missing_openai_api_key")
        return None

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system_prompt or "You are a concise helpful restaurant assistant.",
            },
            {"role": "user", "content": message},
        ],
        "temperature": 0.3,
    }

    try:
        data = call_json_api(
            url="https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            payload=payload,
        )
    except (error.URLError, error.HTTPError, TimeoutError, ValueError) as exc:
        record_ai_status("openai", f"request_failed: {format_provider_error(exc)}")
        return None

    choices = data.get("choices", [])
    if not choices:
        record_ai_status("openai", "no_choices_in_response")
        return None

    answer = choices[0].get("message", {}).get("content")
    if not answer:
        record_ai_status("openai", "empty_content")
        return None

    record_ai_status("openai")
    return answer


def ollama_chat(message: str, system_prompt: Optional[str] = None) -> Optional[str]:
    host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    model = os.getenv("OLLAMA_MODEL", "qwen3:8b")
    prompt = message
    if system_prompt:
        prompt = f"{system_prompt}\n\nUser question: {message}"

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }

    try:
        data = call_json_api(
            url=f"{host.rstrip('/')}/api/generate",
            headers={"Content-Type": "application/json"},
            payload=payload,
            timeout=60,
        )
    except (error.URLError, error.HTTPError, TimeoutError, ValueError) as exc:
        record_ai_status("ollama", f"request_failed: {format_provider_error(exc)}")
        return None

    answer = data.get("response")
    if not answer:
        record_ai_status("ollama", "empty_response")
        return None

    record_ai_status("ollama")
    return answer


class ChatEngine:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._cache: Dict[str, Tuple[str, str]] = {}
        self._cache_order: deque[str] = deque(maxlen=256)
        self._cache_lock = Lock()

    def _knowledge_snapshot(self) -> str:
        name = self.config.get("business_name", "the restaurant")
        address = self.config.get("address", "not listed")
        phone = self.config.get("phone", "not listed")
        reservation = self.config.get("reservation_message", "Call the restaurant for reservations.")
        reservation_url = self.config.get("reservation_url", "")
        happy_hour = self.config.get("happy_hour", {}).get("details", "")
        events = self.config.get("events", [])

        lines = [
            f"Business: {name}",
            f"Address: {address}",
            f"Phone: {phone}",
            f"Reservation guidance: {reservation}",
        ]
        if reservation_url:
            lines.append(f"Reservation URL: {reservation_url}")
        if happy_hour:
            lines.append(f"Happy hour: {happy_hour}")
        if isinstance(events, list) and events:
            event_lines = []
            for item in events[:6]:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                details = item.get("details")
                if name and details:
                    event_lines.append(f"- {name}: {details}")
            if event_lines:
                lines.append("Events:\n" + "\n".join(event_lines))
        return "\n".join(lines)

    def update_config(self, config: Dict[str, Any]) -> None:
        self.config = config
        with self._cache_lock:
            self._cache.clear()
            self._cache_order.clear()

    def _build_grounded_prompt(
        self,
        message: str,
        faq_hint: Optional[Dict[str, str]] = None,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        faq_block = ""
        if faq_hint:
            faq_block = (
                "\nCandidate FAQ (may be partial):\n"
                f"Q: {faq_hint.get('question', '')}\n"
                f"A: {faq_hint.get('answer', '')}\n"
            )

        history_block = ""
        if history:
            recent = history[-8:]
            rendered = []
            for item in recent:
                role = item.get("role", "user")
                content = item.get("content", "")
                if content:
                    rendered.append(f"{role.title()}: {content}")
            if rendered:
                history_block = "\nRecent conversation:\n" + "\n".join(rendered) + "\n"

        return (
            "You are a helpful restaurant assistant. Use the provided business facts first. "
            "Use recent conversation context to resolve follow-up questions and pronouns. "
            "If user intent is unclear, answer the most likely intent briefly and add one clarifying question. "
            "Do not invent facts that are not in provided facts."
            f"\n\nBusiness Facts:\n{self._knowledge_snapshot()}"
            f"{faq_block}"
            f"{history_block}"
            f"\nUser message: {message}"
        )

    def _family_dinner_suggestion(self) -> str:
        menus = self.config.get("menus", {})
        main = menus.get("main", {})
        cocktails = menus.get("cocktails", {})
        kids = menus.get("kids", {})
        happy_hour = self.config.get("happy_hour", {})

        main_items = ", ".join((main.get("popular_items") or [])[:4])
        cocktail_items = ", ".join((cocktails.get("popular_items") or [])[:3])
        kids_items = ", ".join((kids.get("popular_items") or [])[:3])
        hh_time = happy_hour.get("time", "4pm - 6pm daily")

        lines = [
            "Suggested plan for a group dinner:",
            f"- Start with shareables, then mains. Popular picks: {main_items or 'house favorites from the dinner menu.'}",
            f"- Cocktail pairing ideas: {cocktail_items or 'signature cocktails and mocktails.'}",
            f"- If kids are joining: {kids_items or 'kid-friendly menu options are available.'}",
            f"- If timing fits, use happy hour ({hh_time}) for drinks and bites before dinner.",
        ]

        if main.get("url"):
            lines.append(f"- Dinner menu: {main['url']}")
        if cocktails.get("url"):
            lines.append(f"- Cocktail menu: {cocktails['url']}")

        return "\n".join(lines)

    def _hospitality_copy_response(self, message: str) -> Optional[str]:
        text = normalize_text(message)
        keywords = ("welcome", "invite", "caption", "bio", "tagline", "announcement", "social post", "first-time")
        if not any(token in text for token in keywords):
            return None

        name = self.config.get("business_name", "Little Red Wasp")
        address = self.config.get("address", "downtown Fort Worth")
        happy_hour = self.config.get("happy_hour", {}).get("time", "4pm - 6pm daily")
        reservation = self.config.get("reservation_message", "Call us for reservations.")

        return (
            f"Welcome to {name} at {address} - great food, local drafts, and a full bar ready for your night out.\n"
            f"Join us for happy hour ({happy_hour}) and plan ahead: {reservation}"
        )

    def _brand_positioning_response(self) -> str:
        name = self.config.get("business_name", "Little Red Wasp Kitchen + Bar")
        tagline = self.config.get("tagline", "A full-service downtown restaurant and bar.")
        services = self.config.get("services", [])
        core_services = ", ".join(services[:5]) if isinstance(services, list) else "dine-in and full bar service"
        happy_hour = self.config.get("happy_hour", {}).get("details", "Daily happy hour is available.")
        return (
            f"{name} stands out for {tagline}\n"
            f"Guests usually choose us for: {core_services}.\n"
            f"Bonus: {happy_hour}"
        )

    def _fun_fact_response(self) -> str:
        name = self.config.get("business_name", "Little Red Wasp Kitchen + Bar")
        happy_hour = self.config.get("happy_hour", {}).get("time", "4pm - 6pm daily")
        brunch_days = self.config.get("brunch", {}).get("days", "Saturday and Sunday")
        alter_egos = self.config.get("alter_egos", [])
        sibling_names = ", ".join(item.get("name", "") for item in alter_egos if isinstance(item, dict) and item.get("name"))
        sibling_line = f" It is connected to sibling concepts like {sibling_names}." if sibling_names else ""
        return (
            f"Fun fact: {name} runs happy hour {happy_hour} every day and also serves brunch on {brunch_days}."
            f"{sibling_line}"
        )

    def _creative_local_response(self, message: str) -> Optional[str]:
        text = normalize_text(message)
        name = self.config.get("business_name", "Little Red Wasp Kitchen + Bar")
        tagline = self.config.get("tagline", "Straightforward food, local drafts, and a full bar")
        happy_hour = self.config.get("happy_hour", {}).get("time", "4pm - 6pm daily")
        address = self.config.get("address", "downtown Fort Worth")

        if any(token in text for token in ("intro", "introduce", "welcome", "guests tonight", "2-line", "two line")):
            return (
                f"Welcome to {name} in {address} - {tagline}.\n"
                f"Settle in for great food and cocktails, and if you arrive early, happy hour runs {happy_hour}."
            )

        if any(token in text for token in ("chef philosophy", "philosophy", "culinary style", "kitchen style")):
            return (
                f"Our kitchen style is built around {tagline.lower()}, balancing comfort-driven classics with polished execution.\n"
                "We focus on approachable choices that pair naturally with beer, cocktails, and social dining."
            )

        return None

    def _is_menu_comparison_intent(self, text: str) -> bool:
        menu_terms = ("menu", "menus", "dish", "dishes", "food", "drink", "cocktail", "brunch", "dinner", "lunch")
        compare_terms = ("compare", "comparison", "difference", "differences", "recommend", "best", "which is better", "what should we order")
        has_menu_context = any(term in text for term in menu_terms)
        has_compare_context = any(term in text for term in compare_terms)
        return has_menu_context and has_compare_context

    def _is_event_planning_intent(self, text: str) -> bool:
        if "buzz for a cause" in text:
            return True
        planning_terms = ("plan", "roadmap", "organize", "hosting", "host", "schedule", "steps")
        return "event" in text and any(term in text for term in planning_terms)

    def _cached_lookup(self, key: str) -> Optional[Tuple[str, str]]:
        with self._cache_lock:
            return self._cache.get(key)

    def _cache_store(self, key: str, payload: Tuple[str, str]) -> None:
        with self._cache_lock:
            if key not in self._cache:
                self._cache_order.append(key)
            self._cache[key] = payload

            while len(self._cache) > self._cache_order.maxlen:
                oldest_key = self._cache_order.popleft()
                self._cache.pop(oldest_key, None)

    def _rule_response(self, message: str) -> Optional[Tuple[str, str]]:
        text = normalize_text(message)
        config = self.config

        # Multi-intent FAQs should return a combined answer instead of only first-match snippets.
        combined: List[str] = []
        seen = set()

        def add_once(tag: str, value: str) -> None:
            if tag in seen:
                return
            seen.add(tag)
            combined.append(value)

        if "hours" in text or "open" in text:
            add_once("hours", format_hours(config.get("hours", {})))

        if "reservation" in text or "book" in text or "reserve" in text:
            answer = config.get("reservation_message") or "Please call to make a reservation."
            url = config.get("reservation_url")
            if url:
                answer = f"{answer}\nReservation page: {url}"
            add_once("reservation", answer)

        if "phone" in text or "call" in text or "contact" in text:
            phone = config.get("phone", "Not available")
            email = config.get("email", "Not available")
            add_once("contact", f"Phone: {phone}\nEmail: {email}")

        if "address" in text or "located" in text or "location" in text or "where are you" in text:
            address = config.get("address", "Address not available")
            add_once("address", f"Address: {address}")

        if "happy hour" in text:
            hh = config.get("happy_hour", {})
            details = hh.get("details", "Happy hour details are currently unavailable.")
            add_once("happy_hour", details)

        if combined:
            return "\n\n".join(combined), "local_rule"

        if self._is_menu_comparison_intent(text):
            return build_menu_comparison(config), "complex_task"

        if any(token in text for token in ("weekend", "itinerary", "plan weekend")):
            return build_weekend_plan(config), "complex_task"

        if any(token in text for token in ("roadmap", "event planning")) or self._is_event_planning_intent(text):
            return build_event_roadmap(config), "complex_task"

        if any(token in text for token in ("birthday", "celebration", "group dinner", "for 10", "for 12", "for 15", "party")):
            return self._family_dinner_suggestion(), "complex_task"

        if any(token in text for token in ("suggest", "recommend", "what should we order", "what would you suggest")) and any(
            token in text for token in ("dinner", "cocktail", "drinks", "family", "group")
        ):
            return self._family_dinner_suggestion(), "complex_task"

        if any(token in text for token in ("unique", "stand out", "special", "why should", "why choose", "compared to nearby")):
            return self._brand_positioning_response(), "local_rule"

        if any(token in text for token in ("fun fact", "interesting fact", "tell me something", "quick fact")):
            return self._fun_fact_response(), "local_rule"

        hospitality_copy = self._hospitality_copy_response(message)
        if hospitality_copy:
            return hospitality_copy, "local_rule"

        faq_match = faq_match_details(message, config.get("faqs"))
        if faq_match and faq_match["overlap"] >= 2 and faq_match["score"] >= 0.6:
            return faq_match["item"]["answer"], "local_faq"

        return None

    def _ai_response(self, message: str, system_prompt: Optional[str] = None) -> Optional[Tuple[str, str]]:
        provider = os.getenv("AI_PROVIDER", "groq").strip().lower()
        chain_fallback = os.getenv("AI_FALLBACK_CHAIN", "0").strip() == "1"

        if provider == "groq":
            reply = groq_chat(message, system_prompt=system_prompt)
            if reply:
                return reply, "groq"
            if not chain_fallback:
                return None

        if provider == "openai":
            reply = openai_chat(message, system_prompt=system_prompt)
            if reply:
                return reply, "openai"
            if not chain_fallback:
                return None

        if provider == "ollama":
            reply = ollama_chat(message, system_prompt=system_prompt)
            if reply:
                return reply, "ollama"
            if not chain_fallback:
                return None

        # Optional fallback cascade.
        for fallback_provider, fn in (("groq", groq_chat), ("openai", openai_chat), ("ollama", ollama_chat)):
            if fallback_provider == "openai" and not os.getenv("OPENAI_API_KEY", "").strip():
                continue
            if fallback_provider == "groq" and not os.getenv("GROQ_API_KEY", "").strip():
                continue
            reply = fn(message, system_prompt=system_prompt)
            if reply:
                return reply, fallback_provider

        return None

    def _build_cache_key(self, message: str, client_id: str, history: Optional[List[Dict[str, str]]]) -> str:
        latest_user_turn = ""
        if history:
            for item in reversed(history):
                if item.get("role") == "user":
                    latest_user_turn = item.get("content", "")
                    break
        return normalize_text(f"{client_id}|{latest_user_turn}|{message}")

    def chat(self, message: str, client_id: str, history: Optional[List[Dict[str, str]]] = None) -> Tuple[str, str]:
        cache_key = self._build_cache_key(message, client_id, history)
        cached = self._cached_lookup(cache_key)
        if cached:
            return cached

        rule_payload = self._rule_response(message)
        if rule_payload:
            self._cache_store(cache_key, rule_payload)
            return rule_payload

        faq_match = faq_match_details(message, self.config.get("faqs"))
        if faq_match and faq_match["overlap"] >= 2 and faq_match["score"] >= 0.35:
            grounded_prompt = self._build_grounded_prompt(message, faq_hint=faq_match["item"], history=history)
            ai_payload = self._ai_response(message, system_prompt=grounded_prompt)
            if ai_payload:
                answer, source = ai_payload
                hybrid_payload = (answer, f"hybrid_{source}")
                self._cache_store(cache_key, hybrid_payload)
                return hybrid_payload

        ai_payload = self._ai_response(message, system_prompt=self._build_grounded_prompt(message, history=history))
        if ai_payload:
            self._cache_store(cache_key, ai_payload)
            return ai_payload

        creative_local = self._creative_local_response(message)
        if creative_local:
            payload = (creative_local, "local_assist")
            self._cache_store(cache_key, payload)
            return payload

        fallback = (
            "I can still help from local knowledge while AI is temporarily unavailable. "
            "Try asking about hours, reservations, happy hour, menus, brunch, or event planning.",
            "fallback",
        )
        self._cache_store(cache_key, fallback)
        return fallback


def get_client_id(req: Any) -> str:
    raw = (req.headers.get("X-Client-Id") or "").strip()
    if raw:
        return normalize_text(raw)[:80]

    remote = req.remote_addr or "anonymous"
    agent = (req.headers.get("User-Agent") or "ua")[:60]
    return normalize_text(f"{remote}|{agent}")


def get_history(client_id: str) -> List[Dict[str, str]]:
    with CONVERSATION_LOCK:
        convo = CONVERSATIONS.get(client_id)
        if not convo:
            return []
        return list(convo)


def append_turn(client_id: str, role: str, content: str, source: str = "") -> None:
    with CONVERSATION_LOCK:
        convo = CONVERSATIONS.get(client_id)
        if convo is None:
            convo = deque(maxlen=MAX_CONVERSATION_TURNS)
            CONVERSATIONS[client_id] = convo

        turn = {"role": role, "content": content}
        if source:
            turn["source"] = source
        convo.append(turn)


load_env_file(ENV_PATH)
CONFIG = load_config(CONFIG_PATH)
ENGINE = ChatEngine(CONFIG)

METRICS_LOCK = Lock()
LATENCIES_MS: deque[float] = deque(maxlen=200)
TOTAL_REQUESTS = 0
RULE_HITS = 0
AI_HITS = 0
ERRORS = 0

app = Flask(__name__, template_folder="templates", static_folder="static")


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.get("/admin")
def admin() -> Any:
    if not admin_enabled():
        return "Admin is not enabled. Set ADMIN_TOKEN in environment variables.", 404
    return render_template("admin.html")


@app.get("/admin/config")
def admin_config() -> Any:
    if not admin_authorized():
        return jsonify({"error": "Unauthorized"}), 401

    with CONFIG_LOCK:
        return jsonify(CONFIG)


@app.put("/admin/config")
def update_admin_config() -> Any:
    global CONFIG, ENGINE

    if not admin_authorized():
        return jsonify({"error": "Unauthorized"}), 401

    payload = flask_request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Config must be a JSON object."}), 400

    required_fields = ("business_name", "hours", "menus", "faqs")
    missing = [field for field in required_fields if field not in payload]
    if missing:
        return jsonify({"error": f"Missing required field(s): {', '.join(missing)}"}), 400

    try:
        with CONFIG_LOCK:
            save_config(CONFIG_PATH, payload)
            CONFIG = payload
            ENGINE.update_config(CONFIG)
    except (OSError, TypeError, ValueError) as exc:
        return jsonify({"error": f"Unable to save config: {exc}"}), 500

    return jsonify({"ok": True, "message": "Knowledge base updated and reloaded."})


@app.get("/status")
def status() -> Any:
    with METRICS_LOCK:
        avg_latency = round(sum(LATENCIES_MS) / len(LATENCIES_MS), 2) if LATENCIES_MS else 0.0
    with AI_STATUS_LOCK:
        ai_diag = {
            "last_provider": LAST_AI_PROVIDER,
            "last_error": LAST_AI_ERROR,
            "last_attempt_at": LAST_AI_ATTEMPT_AT,
        }

    with METRICS_LOCK:
        payload = {
            "provider": os.getenv("AI_PROVIDER", "groq"),
            "ai_diagnostics": ai_diag,
            "metrics": {
                "avg_latency_ms": avg_latency,
                "total_requests": TOTAL_REQUESTS,
                "rule_hits": RULE_HITS,
                "ai_hits": AI_HITS,
                "errors": ERRORS,
            },
            "conversation": {
                "active_clients": len(CONVERSATIONS),
                "max_turns": MAX_CONVERSATION_TURNS,
            },
        }
    return jsonify(payload)


@app.post("/chat")
def chat() -> Any:
    global TOTAL_REQUESTS, RULE_HITS, AI_HITS, ERRORS

    started = time.perf_counter()
    body = flask_request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    client_id = get_client_id(flask_request)

    if not message:
        return jsonify({"reply": "Please type a message.", "source": "validation"}), 400

    try:
        history = get_history(client_id)
        reply, source = ENGINE.chat(message, client_id=client_id, history=history)
        append_turn(client_id, "user", message)
        append_turn(client_id, "assistant", reply, source=source)
        with METRICS_LOCK:
            TOTAL_REQUESTS += 1
            if source.startswith("local") or source == "complex_task":
                RULE_HITS += 1
            elif source in {"groq", "openai", "ollama"} or source.startswith("hybrid_"):
                AI_HITS += 1
        return jsonify({"reply": reply, "source": source})
    except Exception:
        with METRICS_LOCK:
            ERRORS += 1
        return jsonify({"reply": "Something went wrong while handling your request.", "source": "server_error"}), 500
    finally:
        elapsed = (time.perf_counter() - started) * 1000
        with METRICS_LOCK:
            LATENCIES_MS.append(elapsed)


def get_port() -> int:
    raw_port = os.getenv("PORT", "5001").strip()
    if raw_port.isdigit():
        return int(raw_port)
    return 5001


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    app.run(host=host, port=get_port(), debug=False)
