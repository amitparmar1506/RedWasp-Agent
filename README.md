# Little Red Wasp Chatbot - Ultimate Legend Edition

Hybrid chatbot with:

- Fast local knowledge-base and FAQ matching
- Complex-task planning responses (comparisons, event roadmaps, itinerary prompts)
- AI fallback (Groq, OpenAI, or Ollama)
- Modern web UI with responsive layout, quick mission buttons, and live status chips

## Run The Website

```powershell
python app.py
```

Open:

```text
http://127.0.0.1:5001/
```

## What Was Upgraded

- New frontend files:
	- `templates/index.html`
	- `static/styles.css`
	- `static/app.js`
- Better Flask wiring for local template/static folders
- New `/status` endpoint for provider + runtime metrics
- Cached rule/FAQ routing for better efficiency
- Complex-task handler for prompts like:
	- "Compare menus"
	- "Plan weekend itinerary"
	- "Step by step event roadmap"

## Demo AI Provider

The default demo provider is Groq with Llama 3.1 8B Instant:

```powershell
$env:GROQ_API_KEY="your-groq-api-key"
python app.py
```

You can also create a local `.env` file next to `app.py`:

```text
GROQ_API_KEY=your-groq-api-key
AI_PROVIDER=groq
PORT=5002
```

Useful demo environment variables:

```text
AI_PROVIDER=groq
GROQ_API_KEY=your-groq-api-key
GROQ_MODEL=llama-3.1-8b-instant
PORT=5001
```

## Free Local AI

Ollama is still available for local-only demos:

```powershell
$env:AI_PROVIDER="ollama"
ollama pull qwen3:8b
ollama serve
python app.py
```

Optional model changes:

```powershell
$env:OLLAMA_MODEL="qwen3:14b"
python app.py
```

Optional provider changes:

```powershell
$env:AI_PROVIDER="openai"
$env:OPENAI_API_KEY="your-key"
python app.py
```

Useful environment variables:

```text
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:8b

## Status Endpoint

You can inspect runtime health and routing metrics:

```text
GET /status
```
```
