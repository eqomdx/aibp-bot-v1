# Meeting Transcript Agent

## What it does
This is a project-management meeting agent, currently at Phase 3. It reads a meeting transcript in Markdown and uses an LLM provider to:

1. **Summarise the meeting** (Phase 1). The summary is saved as `summary.md`.
2. **Extract structured project items** (Phase 2): actions, decisions, risks, issues, dependencies and assumptions, plus a list of missing information. These are saved as `project_items.json` for automation and as `project_items.md` for people to read.
3. **Answer questions about the meeting** (Phase 3), such as "What did we decide about SharePoint?" or "Who owns the Friday demo?"

You pick the provider with `LLM_PROVIDER`:

- `mock` returns fixed example output. It needs no credentials and makes no network calls, so use it for development and demos while no Azure key is available.
- `azure` sends the transcript to an **Azure OpenAI** deployment, such as GPT-4.1 Nano.

The summary has these sections: overview, key discussion points, decisions, actions, risks and issues, and open questions. The model is told to use only what the transcript says. It must not invent owners, deadlines or decisions, and it must keep "suggested" separate from "agreed". A section with nothing to report says "None identified."

Each project item has these fields: type, description, owner, due date, source and confidence. The rules are:

- **Owner** and **due date** are filled in only when the transcript states them. Otherwise they are `null`, shown as "Not stated". A due date keeps the transcript's own words, such as "Friday", and is never turned into a calendar date.
- **Source** is a quote copied word for word from the transcript. The app checks each quote against the transcript itself and does not rely on the model for this. If a quote can't be found, the item is kept but marked `source_verified: false`, and `project_items.md` flags it `NOT FOUND IN TRANSCRIPT`. This catches items the model invented.
- **Confidence** is `high` when something was stated or agreed outright, `medium` when it was tentative, conditional or has no clear owner, and `low` when it was only implied.

**Missing-information checks** then go through the items to list what still needs following up. They follow fixed rules and make no model call:

| Item type | Flagged when |
|---|---|
| Action | No owner, or no due date |
| Risk, Issue, Dependency | No owner |
| Any item | Its source quote is not found in the transcript, or its confidence is low |

The rules live in `REQUIRED_FIELDS` in `missing_information.py`. Edit that table to change what counts as missing.

This app is built independently of Copilot Studio. The meeting logic sits behind a provider interface, so a different model service can replace Azure OpenAI later without rewriting that logic. The same applies to a different front end, such as Copilot Studio, Teams or a web API.

## Setup
You need Python 3.11 or newer.

```bash
python -m venv .venv
```

Activate the environment:

| Shell | Command |
|---|---|
| Windows PowerShell | `.venv\Scripts\Activate.ps1` |
| Windows cmd | `.venv\Scripts\activate.bat` |
| macOS / Linux | `source .venv/bin/activate` |
| Git Bash | `source .venv/Scripts/activate` |

Install the dependencies. This also installs the `meeting_agent` package in editable mode:

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env`. It starts with the mock provider selected, so this runs straight away with no credentials:

```env
LLM_PROVIDER=mock
```

The mock always returns the same example output, written for the sample `transcript.md`. The summary's Overview labels it as mock output. The mock does not read the transcript. If you run it on a different transcript, every project item is flagged `NOT FOUND IN TRANSCRIPT`, so mock output can't pass for a real extraction.

### Switching to Azure OpenAI
Set this in `.env`:

```env
LLM_PROVIDER=azure
```

Then fill in the Azure settings. The app reads them only when `LLM_PROVIDER=azure`.

| Variable | Meaning |
|---|---|
| `AZURE_OPENAI_ENDPOINT` | Your Azure OpenAI resource endpoint, e.g. `https://<resource>.cognitiveservices.azure.com/` |
| `OPENAI_API_KEY` | A key for **that Azure resource**. It is sent only to the Azure endpoint, never to `api.openai.com`. |
| `OPENAI_API_VERSION` | Azure OpenAI API version, e.g. `2024-12-01-preview` |
| `CHAT_MODEL` | The **Azure deployment name**. |
| `EMBEDDING_MODEL` | Optional. Not used yet; reserved for later Q&A work. |

`CHAT_MODEL` must be the name you gave the deployment in Azure AI Foundry. That can differ from the underlying model's name. If the two differ, use the deployment name. If the deployment is not found, the app tells you to check `CHAT_MODEL`.

`.env` is git-ignored. Never commit it.

## Usage

```bash
python -m meeting_agent.main transcript.md
```

- If you leave out the path, the app uses `transcript.md` in the current folder.
- `-o path/to/folder` writes the output files to another folder.

Expected problems print one line and exit with code 1. No traceback is shown. Examples:

```text
Error: Transcript file 'transcript.md' was not found.
Error: Transcript contains no usable text.
Error: LLM_PROVIDER is not configured. Set it to 'mock' or 'azure' ...
Error: AZURE_OPENAI_ENDPOINT is not configured. ...   (LLM_PROVIDER=azure only)
```

### Asking questions

```bash
python -m meeting_agent.ask transcript.md -q "What did we decide about SharePoint?"
python -m meeting_agent.ask transcript.md
```

- `-q` asks one question. Repeat `-q` to ask several; later questions can refer back to earlier ones.
- Leave out `-q` to start an interactive session. Type a question at `Question>`. Type `exit`, press Ctrl+C or Ctrl+Z to stop.
- Follow-up questions such as "Who owns it?" work, because the last five questions and answers are sent along with each new question.

The model answers from the transcript alone, as JSON with an answer and supporting quotes. The app then checks each quote against the transcript:

```text
Q: What did we decide about SharePoint?
The team agreed to use SharePoint for RAID data in the first version. ...

Sources:
  - "For the RAID data, I think we should initially use SharePoint."
  - "Yes, SharePoint makes sense for the first version. We can revisit Planner later."
```

- If the transcript doesn't cover the question, the answer says so and gives no sources.
- A quote that isn't in the transcript is marked `(NOT FOUND IN TRANSCRIPT)`, and the answer carries a warning.
- In an interactive session, an error on one question doesn't end the session.

With `LLM_PROVIDER=mock`, only the three example questions from the brief get answers, covering SharePoint, the demo and risks. Every other question gets a "no example answer" reply.

There is no knowledge store yet. Every question is answered from one transcript, sent to the model in full. Embeddings or retrieval become worth adding once questions need to span several meetings.

## Output
Three files are written to the transcript's folder. Each run overwrites them.

| File | Contents |
|---|---|
| `summary.md` | The meeting summary |
| `project_items.json` | `{"transcript", "items": [{type, description, owner, due_date, source, confidence, source_verified}], "missing_information": [{item_number, item_type, item_description, gap, message}]}`, ready for Power Automate and SharePoint later. `item_number` is the item's 1-based position in `items`. |
| `project_items.md` | The same items as tables, one section per type, then a **Missing Information** section |

The summary and the item tables are also printed to the terminal. If any step fails, no files are written. That covers an empty model reply and an extraction reply that isn't valid JSON.

## Tests

```bash
pytest
```

The tests use the mock provider or a faked Azure SDK. They make no network calls, use no tokens, and never need or print a real key.

## Architecture

```text
transcript.md -> load_transcript()           transcript.py
              -> MeetingService              meeting_service.py  (meeting logic, no provider code)
                   .summarise()         -> Markdown summary
                   .extract_items()     -> list[ProjectItem]  (project_items.py parses and verifies)
                   .find_missing_information(items) -> gaps   (missing_information.py, no LLM)
                   .answer_question(transcript, question, history) -> Answer  (qa.py parses and verifies)
              -> LLMProvider.generate()      providers/base.py   (interface)
                   ├── MockLLMProvider       providers/mock.py          LLM_PROVIDER=mock
                   └── AzureOpenAIProvider   providers/azure_openai.py  LLM_PROVIDER=azure
              -> summary.md, project_items.json, project_items.md   output.py
```

`providers/factory.py` maps `LLM_PROVIDER` to a provider. It creates only the provider you selected, so the mock never reads the Azure settings. Switching providers changes that one setting. `MeetingService` stays the same.

```text
src/meeting_agent/
  config.py              reads and checks the Azure settings from .env
  transcript.py          loads and validates transcript files (no LLM code)
  prompts.py             system prompts, summary template, extraction JSON schema
  meeting_service.py     MeetingService: summarise(), extract_items(), find_missing_information(), answer_question()
  project_items.py       ProjectItem model, JSON parsing, source verification, Markdown tables
  missing_information.py rule-based gap checks (missing owner / due date / unverified source / low confidence)
  qa.py                  Answer model, JSON parsing, quote verification, answer text
  llm_output.py          shared JSON-reply parsing and quote matching
  providers/base.py      LLMProvider protocol: generate(system_prompt, user_prompt) -> str
  providers/mock.py      MockLLMProvider: fixed example replies (summary, items, 3 example answers), no network
  providers/azure_openai.py  Azure OpenAI chat-completions adapter and error translation
  providers/factory.py   create_provider(LLM_PROVIDER) -> the selected provider
  output.py              writes Markdown and JSON files
  errors.py              user-facing error types
  app.py                 build_service(): shared wiring for every interface
  main.py                process command: summary + items + missing information
  ask.py                 Q&A command: one-shot or interactive; owns the conversation history
tests/                   pytest suite, Azure mocked
```

To add another LLM, write a class with a `generate(system_prompt, user_prompt) -> str` method. Then register it in `PROVIDER_BUILDERS` in `providers/factory.py`.
