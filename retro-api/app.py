import os
import json
import base64
import tempfile
import requests
import uvicorn
import logging
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import asyncio

# LangChain and Chroma imports
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_huggingface.embeddings import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

# PDF & Image processing
import fitz  # PyMuPDF
from PIL import Image
from io import BytesIO
import pytesseract

# CLIP for image embeddings
from transformers import CLIPProcessor, CLIPModel
import torch

# ------------------ Logging Setup ------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("retro-api")

# ------------------ Environment Setup ------------------
load_dotenv()
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
OPENROUTER_URL = os.getenv("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "qwen/qwen2.5-vl-72b-instruct")
TESSERACT_CMD = os.getenv("TESSERACT_CMD")
if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
if not OPENROUTER_KEY:
    logger.warning("OPENROUTER_KEY is not set; /query will fail until it is added to .env")

# ------------------ LangChain / Chroma Setup ------------------
TEXT_PERSIST_DIR = "chroma_text_db"
IMAGE_PERSIST_DIR = "chroma_image_db"
for d in [TEXT_PERSIST_DIR, IMAGE_PERSIST_DIR]:
    os.makedirs(d, exist_ok=True)

# Initialize HuggingFaceEmbeddings with the nomic model
text_embeddings = HuggingFaceEmbeddings(
    model_name="nomic-ai/nomic-embed-text-v1.5",
    model_kwargs={"trust_remote_code": True}
)

# Global vectorstores for text and images
text_vectorstore = None
image_vectorstore = None


class IdentityEmbedding:
    """Placeholder embedding for the image store; CLIP vectors are added directly."""
    def embed_documents(self, texts):
        return texts


def load_vectorstores():
    global text_vectorstore, image_vectorstore
    try:
        text_vectorstore = Chroma(
            persist_directory=TEXT_PERSIST_DIR,
            embedding_function=text_embeddings
        )
        logger.info("Loaded existing text vectorstore.")
    except Exception as e:
        logger.error("Error loading text vectorstore: %s", e)
        text_vectorstore = None
    try:
        image_vectorstore = Chroma(
            persist_directory=IMAGE_PERSIST_DIR,
            embedding_function=IdentityEmbedding()
        )
        logger.info("Loaded existing image vectorstore.")
    except Exception as e:
        logger.error("Error loading image vectorstore: %s", e)
        image_vectorstore = None

load_vectorstores()

# ------------------ CLIP Setup for Image Embeddings ------------------
clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

async def get_clip_image_embedding_async(image):
    return await asyncio.to_thread(get_clip_image_embedding, image)

def get_clip_image_embedding(image):
    inputs = clip_processor(images=image, return_tensors="pt")
    with torch.no_grad():
        features = clip_model.get_image_features(**inputs)
    return features.squeeze().tolist()

def get_clip_text_embedding(text):
    # CLIP's text encoder only accepts 77 tokens, so long queries are truncated
    inputs = clip_processor(text=[text], return_tensors="pt", padding=True, truncation=True)
    with torch.no_grad():
        features = clip_model.get_text_features(**inputs)
    return features.squeeze().tolist()

# ------------------ Helper Functions ------------------

async def process_single_image(image, page_num, img_index, filename):
    try:
        img_id = f"{filename}_p{page_num}_i{img_index}"

        # Run embedding + OCR in parallel
        emb_task = get_clip_image_embedding_async(image)
        ocr_task = ocr_image_async(image)
        emb, ocr_text = await asyncio.gather(emb_task, ocr_task)

        buffered = BytesIO()
        image.save(buffered, format="JPEG")
        img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

        meta = {
            "filename": filename,
            "page_num": page_num,
            "image_index": img_index,
            "source": "image_clip",
            "image_b64": img_b64
        }

        return img_id, emb, meta, ocr_text.strip()

    except Exception as e:
        logger.error(f"Failed to process image {img_index} on page {page_num}: {e}")
        return None


def extract_images_from_pdf(pdf_path):
    """
    Extract images from the PDF using PyMuPDF.
    Returns a list of tuples: (PIL.Image, page_num, image_index).
    """
    images = []
    with fitz.open(pdf_path) as doc:
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            image_list = page.get_images(full=True)
            logger.info(f"Page {page_num+1}: Found {len(image_list)} images.")
            for img_index, img in enumerate(image_list):
                try:
                    xref = img[0]
                    base_image = doc.extract_image(xref)
                    image_bytes = base_image["image"]
                    image = Image.open(BytesIO(image_bytes)).convert("RGB")
                    images.append((image, page_num + 1, img_index + 1))
                except Exception as e:
                    logger.error(f"Error processing image {img_index+1} on page {page_num+1}: {e}")
    return images

def ocr_image(image):
    """
    Use Tesseract OCR to extract text from a PIL Image.
    """
    try:
        text = pytesseract.image_to_string(image)
        return text.strip()
    except Exception as e:
        logger.error(f"OCR error: {e}")
        return ""


async def ocr_image_async(image):
    return await asyncio.to_thread(ocr_image, image)


# ------------------ FastAPI App Setup ------------------
app = FastAPI(title="RetroDoc retro-api")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------ Endpoints ------------------

@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    temp_path = None
    try:
        logger.info(f"Received upload for file: {file.filename}")
        file_bytes = await file.read()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
            f.write(file_bytes)
            temp_path = f.name

        loader = PyMuPDFLoader(temp_path)
        docs = loader.load()
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        text_docs = splitter.split_documents(docs)

        for doc in text_docs:
            doc.metadata["filename"] = file.filename
            doc.metadata["source"] = "text"

        images = extract_images_from_pdf(temp_path)
        ocr_docs = []
        image_ids, image_embeddings, image_metadatas, image_contents = [], [], [], []

        # Async embedding and OCR
        tasks = []
        for image, page_num, img_index in images:
            tasks.append(process_single_image(image, page_num, img_index, file.filename))

        results = await asyncio.gather(*tasks)

        for res in results:
            if res is None:
                continue
            img_id, emb, meta, ocr_text = res
            image_ids.append(img_id)
            image_embeddings.append(emb)
            image_metadatas.append(meta)
            image_contents.append(f"image_{img_id}")

            if ocr_text:
                ocr_docs.append(Document(
                    page_content=ocr_text,
                    metadata={
                        "filename": file.filename,
                        "page_num": meta["page_num"],
                        "image_index": meta["image_index"],
                        "source": "image_ocr"
                    }
                ))

        all_text_docs = text_docs + ocr_docs

        global text_vectorstore, image_vectorstore
        if all_text_docs:
            if text_vectorstore is None:
                text_vectorstore = Chroma.from_documents(
                    all_text_docs,
                    text_embeddings,
                    persist_directory=TEXT_PERSIST_DIR
                )
            else:
                text_vectorstore.add_documents(all_text_docs)

        if image_ids:
            if image_vectorstore is None:
                image_vectorstore = Chroma(
                    persist_directory=IMAGE_PERSIST_DIR,
                    embedding_function=IdentityEmbedding()
                )
            image_vectorstore._collection.add(
                ids=image_ids,
                embeddings=image_embeddings,
                metadatas=image_metadatas,
                documents=image_contents
            )

        return {"status": "processed", "filename": file.filename, "num_docs": len(all_text_docs) + len(image_ids)}

    except Exception as e:
        logger.error(f"Error in upload: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


@app.post("/query")
async def query(q: str = Form(...), allowed_files: str = Form(None)):
    """
    Query endpoint: Performs a similarity search on both text and image vectorstores,
    builds a prompt from the retrieved text segments, and calls OpenRouter to generate a response.
    """
    try:
        logger.info(f"Received query: {q}")
        allowed_filenames = [f for f in allowed_files.split(",") if f] if allowed_files else []
        file_filter = {"filename": {"$in": allowed_filenames}} if allowed_filenames else None

        if text_vectorstore is None:
            return {
                "query": q,
                "retrieved_context": [],
                "retrieved_images": [],
                "generated_response": "No documents available."
            }

        # Text similarity search
        text_docs = text_vectorstore.similarity_search(q, k=10, filter=file_filter)

        retrieved_texts = []
        for doc in text_docs:
            retrieved_texts.append({
                "text": doc.page_content,
                "filename": doc.metadata.get("filename", "unknown"),
                "page_num": doc.metadata.get("page_num", doc.metadata.get("page", 0)),
                "source": doc.metadata.get("source", "text")
            })

        # Image similarity search
        retrieved_images = []
        if image_vectorstore is not None:
            try:
                # Encode the query with CLIP's text encoder so it matches the stored CLIP image embeddings
                query_embedding = get_clip_text_embedding(q)

                results = image_vectorstore._collection.query(
                    query_embeddings=[query_embedding],
                    n_results=3,
                    include=["metadatas", "documents", "distances"],
                    where=file_filter
                )

                if results and results.get("metadatas"):
                    for metadata in results["metadatas"][0]:  # First (and only) query results
                        if "image_b64" in metadata:
                            retrieved_images.append({
                                "filename": metadata.get("filename", "unknown"),
                                "page_num": metadata.get("page_num", 0),
                                "image_b64": metadata.get("image_b64"),
                                "source": metadata.get("source", "image_clip")
                            })
            except Exception as img_search_error:
                logger.error(f"Error in image search: {img_search_error}")
                # Continue with text results if image search fails

        # Build prompt from retrieved texts
        prompt = f"Query: {q}\n\nContext from documents:\n"
        for i, txt_ctx in enumerate(retrieved_texts):
            prompt += f"\nText {i+1} from {txt_ctx['filename']} (Page {txt_ctx['page_num']}):\n{txt_ctx['text']}\n"

        if retrieved_images:
            prompt += "\nThe following images were also retrieved as relevant to your query:\n"
            for i, img in enumerate(retrieved_images):
                prompt += f"Image {i} from {img['filename']} (Page {img['page_num']})\n"

        images_to_send = [f"data:image/jpeg;base64,{img['image_b64']}" for img in retrieved_images]

        response = await asyncio.to_thread(call_openrouter, prompt, images_to_send)

        try:
            structured_response = json.loads(response)
        except Exception as parse_error:
            logger.error(f"Error parsing response as JSON: {parse_error}")
            structured_response = {
                "valid_images": [],
                "text_analysis": "",
                "image_analysis": [],
                "final_answer": response
            }

        # Keep only the images the model marked as relevant, with their matching analysis
        image_analysis_list = structured_response.get("image_analysis") or []
        filtered_images = []
        filtered_image_analysis = []
        for idx in structured_response.get("valid_images") or []:
            if isinstance(idx, int) and 0 <= idx < len(retrieved_images):
                filtered_images.append(retrieved_images[idx])
                if idx < len(image_analysis_list):
                    filtered_image_analysis.append(image_analysis_list[idx])
                else:
                    filtered_image_analysis.append("No analysis available.")
            else:
                logger.warning(f"Invalid index {idx} in valid_images; skipping")

        structured_response["image_analysis"] = filtered_image_analysis

        return {
            "query": q,
            "retrieved_context": retrieved_texts,
            "retrieved_images": filtered_images,
            "generated_response": structured_response
        }
    except Exception as e:
        logger.error(f"Error in query: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/stats")
async def get_stats():
    """
    Get statistics about unique filenames stored in both vectorstores.
    """
    try:
        filenames = set()

        for vectorstore in [text_vectorstore, image_vectorstore]:
            if vectorstore is not None:
                data = vectorstore.get(include=["metadatas"])
                for meta in data["metadatas"]:
                    filename = meta.get("filename")
                    if filename:
                        filenames.add(filename)

        return {"unique_files": len(filenames), "filenames": sorted(filenames)}

    except Exception as e:
        logger.exception("Error getting vectorstore stats")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.delete("/delete_document")
async def delete_document(filename: str):
    """
    Delete all documents from both vectorstores where metadata contains the given filename.
    """
    try:
        deleted_count = 0
        for vectorstore in [text_vectorstore, image_vectorstore]:
            if vectorstore is not None:
                data = vectorstore.get(where={"filename": filename}, include=[])
                ids_to_delete = data["ids"]
                if ids_to_delete:
                    vectorstore.delete(ids=ids_to_delete)
                    deleted_count += len(ids_to_delete)

        return {"status": "deleted", "filename": filename, "count": deleted_count}

    except Exception as e:
        logger.exception(f"Error deleting documents for {filename}")
        return JSONResponse(status_code=500, content={"error": str(e)})


def call_openrouter(prompt: str, images: list = None) -> str:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "X-Title": "RetroDoc"
    }

    system_message = (
        "You are an AI assistant specializing in multimodal document analysis. "
        "You will receive a user query, text-based context (retrieved documents), and optionally, images. "
        "Your job is to:\n"
        "1. Determine whether each image is valid (i.e., useful and relevant to the query).\n"
        "2. Include a list of the valid image indices under 'valid_images'.\n"
        "3. Analyze the text and each image in depth.\n"
        "4. Provide a well-structured final answer using both modalities.\n\n"
        "Format your response as a JSON object:\n"
        "{\n"
        "  \"valid_images\": [indices of valid images],\n"
        "  \"text_analysis\": \"Analysis of the text-based context\",\n"
        "  \"image_analysis\": [\"Analysis of image 0\", \"Analysis of image 1\", ...],\n"
        "  \"final_answer\": \"Complete and concise answer\"\n"
        "}\n\n"
        "Images are numbered from 0 in the order they are given. 'valid_images' is a list of those 0-based indices (e.g., [0, 2]); "
        "use an empty list if no image is valid. 'image_analysis' must have exactly one entry per input image, in the same order. "
        "Base your answer strictly on the provided context. If there's not enough information, say so clearly."
    )

    messages = [{"role": "system", "content": system_message}]

    # Build user message with images and prompt
    content = [{"type": "text", "text": prompt}]
    for img_url in images or []:
        if img_url.startswith("data:image/"):
            content.append({
                "type": "image_url",
                "image_url": {"url": img_url}
            })
    messages.append({"role": "user", "content": content})

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 8192,
        "response_format": {"type": "json_object"}
    }

    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=180)
        if response.ok:
            data = response.json()
            logger.info("OpenRouter response received")
            return data["choices"][0]["message"]["content"]
        else:
            logger.warning(f"Failed OpenRouter call: {response.status_code}")
            return json.dumps({
                "valid_images": [],
                "text_analysis": "",
                "image_analysis": [],
                "final_answer": f"Error: {response.status_code}. Details: {response.text[:150]}..."
            })
    except Exception as e:
        logger.error(f"Exception during OpenRouter call: {e}")
        return json.dumps({
            "valid_images": [],
            "text_analysis": "",
            "image_analysis": [],
            "final_answer": f"Exception: {str(e)}"
        })

if __name__ == "__main__":
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")))
