# RetroDoc

**Your retro document analyzer.** RetroDoc lets you search and analyze your PDFs in plain English. It reads both the text and the pictures inside them (diagrams, charts, scanned pages), so answers can draw on either.

## What it does

- **Builds a searchable library.** Upload PDFs and RetroDoc indexes their text, their images, and any text inside those images (using OCR).
- **Answers from your documents only.** Type something like *"How does multi-head attention work?"* or *"Summarize the results table"*. RetroDoc finds the most relevant passages and images and writes an answer based only on them.
- **Shows its sources.** Every answer lists the passages it used, with file name and page number, and shows the relevant images with a short analysis of each. Irrelevant images are filtered out.
- **Lets you pick which documents to search.** Enable or disable individual files in the sidebar, or delete them from the library.

It's built as a multimodal RAG (retrieval-augmented generation) system in two parts:

- **retro-frontend:** React 19 + Vite + Tailwind, with a retro-styled UI
- **retro-api:** FastAPI + Chroma + CLIP + Tesseract, answering with a vision-language model on OpenRouter

## How it works

**When you upload a PDF**
1. The text is extracted with PyMuPDF and split into 1000-character chunks with 100 characters of overlap.
2. Each embedded image is extracted, then:
   - embedded with **CLIP** (`openai/clip-vit-base-patch32`) and stored in the image vector store
   - run through **Tesseract OCR**, with the OCR text added to the text store
3. Text chunks and OCR text are embedded with **nomic-embed-text-v1.5** and stored in Chroma.

**When you search your documents**
1. The top 10 text chunks are retrieved by semantic search.
2. The top 3 images are retrieved by encoding your query with CLIP's text encoder.
3. The text and the images are sent to a vision model (Qwen2.5-VL by default). It decides which images are relevant, analyzes them and writes the answer.
4. The UI shows the answer, the source snippets, and the relevant images (click an image to zoom).

Searches only cover the files that are **Enabled** in the sidebar.

## Prerequisites

- Python 3.10+ (developed on 3.12)
- Node.js 18+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract)
  - Windows: install from [UB Mannheim builds](https://github.com/UB-Mannheim/tesseract/wiki), then add it to `PATH` or set `TESSERACT_CMD` in `.env`
  - macOS: `brew install tesseract`
  - Linux: `sudo apt install tesseract-ocr`
- An [OpenRouter API key](https://openrouter.ai/keys)

The first retro-api start downloads the embedding and CLIP models (about 1 GB) from Hugging Face.

## Setup

### 1. retro-api (backend)

```bash
cd retro-api
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
```

Edit `retro-api/.env` and set `OPENROUTER_KEY`. Then start the server:

```bash
python app.py
```

The API runs on http://localhost:8000. Interactive docs are at http://localhost:8000/docs.

### 2. retro-frontend

In a second terminal:

```bash
cd retro-frontend
npm install
npm run dev
```

Open http://localhost:5173.

If retro-api isn't on `localhost:8000`, copy `retro-frontend/.env.example` to `retro-frontend/.env` and set `VITE_API_URL`.

## Configuration

retro-api options, set in `retro-api/.env`:

| Variable | Default | Description |
|---|---|---|
| `OPENROUTER_KEY` | none (required) | OpenRouter API key |
| `OPENROUTER_MODEL` | `qwen/qwen2.5-vl-72b-instruct` | Any OpenRouter model that accepts images |
| `OPENROUTER_URL` | OpenRouter chat completions URL | Override for a compatible endpoint |
| `TESSERACT_CMD` | `tesseract` on PATH | Full path to the Tesseract executable |
| `CORS_ORIGINS` | `*` | Comma-separated list of allowed origins |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Address the server binds to |

retro-frontend option, set in `retro-frontend/.env`:

| Variable | Default |
|---|---|
| `VITE_API_URL` | `http://localhost:8000` |

## API

| Method | Path | Body / params | Description |
|---|---|---|---|
| `POST` | `/upload` | form-data `file` (PDF) | Index a PDF's text, OCR text and images |
| `POST` | `/query` | form-data `q`, `allowed_files` (comma-separated, optional) | Search the enabled documents and generate an answer |
| `GET` | `/stats` | none | List indexed files |
| `DELETE` | `/delete_document` | query `filename` | Remove a file from both stores |

## Data

Vector stores are saved in `retro-api/chroma_text_db/` and `retro-api/chroma_image_db/`. Neither is committed to git. To start fresh, delete both folders.

## Project structure

```
RetroDoc/
├── retro-api/
│   ├── app.py              # FastAPI app: ingestion, retrieval, LLM call
│   ├── requirements.txt
│   └── .env.example
└── retro-frontend/
    ├── src/App.jsx         # UI
    ├── src/App.css         # retro styling
    └── .env.example
```
