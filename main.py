

"""Image -> OpenCV -> OCR -> extracted text -> cleaning -> chunking -> embeddings
-> ChromaDB; user question -> retriever -> Groq LLM -> answer.
"""

import os
import re
import uuid
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, Field

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_EXTRACTED_CHARACTERS = 25_000


def configure_tesseract() -> None:
    configured = os.getenv("TESSERACT_CMD")
    if configured and os.path.exists(configured):
        pytesseract.pytesseract.tesseract_cmd = configured
        return

    candidates = [
        configured,
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        r"C:\Users\deshm\AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            pytesseract.pytesseract.tesseract_cmd = candidate
            os.environ["TESSERACT_CMD"] = candidate
            return


configure_tesseract()

app = FastAPI(title="Framewise Image RAG", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class QuestionRequest(BaseModel):
    image_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=3, max_length=1000)


@lru_cache(maxsize=1)
def get_embeddings() -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")


@lru_cache(maxsize=1)
def get_vector_store() -> Chroma:
    return Chroma(
        collection_name="image_documents",
        embedding_function=get_embeddings(),
        persist_directory=os.getenv("CHROMA_DIR", str(BASE_DIR / "chroma_db")),
    )


def extract_image_text(image_bytes: bytes) -> str:
    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="That file could not be read as an image.")

    height, width = image.shape[:2]
    if max(height, width) > 2400:
        scale = 2400 / max(height, width)
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    processed = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

    try:
        text = pytesseract.image_to_string(processed, config="--oem 3 --psm 6")
    except pytesseract.pytesseract.TesseractNotFoundError as error:
        raise HTTPException(
            status_code=503,
            detail="Tesseract OCR is not installed or TESSERACT_CMD is not configured.",
        ) from error

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"-\s*\n\s*", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise HTTPException(
            status_code=422,
            detail="No readable text was found. Try a sharper image with clearer lighting.",
        )
    return text[:MAX_EXTRACTED_CHARACTERS]


def index_image(image_bytes: bytes, filename: str) -> dict[str, object]:
    text = extract_image_text(image_bytes)
    chunks = RecursiveCharacterTextSplitter(
        chunk_size=900,
        chunk_overlap=150,
        separators=["\n\n", "\n", ". ", " ", ""],
    ).split_text(text)
    image_id = str(uuid.uuid4())
    get_vector_store().add_texts(
        texts=chunks,
        metadatas=[{"image_id": image_id, "chunk_index": index} for index in range(len(chunks))],
        ids=[f"{image_id}-{index}" for index in range(len(chunks))],
    )
    return {
        "image_id": image_id,
        "filename": Path(filename or "image").name,
        "text": text,
        "character_count": len(text),
        "chunk_count": len(chunks),
    }


def answer_image_question(image_id: str, question: str) -> dict[str, object]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="Add your Groq API key to .env to enable answers.")

    try:
        retriever = get_vector_store().as_retriever(
            search_type="similarity",
            search_kwargs={"k": 4, "filter": {"image_id": image_id}},
        )
        documents = retriever.invoke(question)
    except Exception as error:
        raise HTTPException(status_code=503, detail="The document index is not available yet.") from error
    if not documents:
        raise HTTPException(status_code=404, detail="Process an image before asking a question.")

    context = "\n\n---\n\n".join(document.page_content for document in documents)
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "Answer using only the supplied document excerpts. If the answer is not present, "
                "say you could not find it in this image. Keep the answer clear and concise.",
            ),
            ("human", "Document excerpts:\n{context}\n\nQuestion: {question}"),
        ]
    )
    try:
        model = ChatGroq(
            model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            temperature=0.2,
            api_key=api_key,
        )
        response = model.invoke(prompt.format_messages(context=context, question=question))
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=f"The Groq model could not answer this question: {error}",
        ) from error

    return {
        "answer": response.content,
        "sources": [document.page_content[:260].strip() for document in documents],
    }


@app.get("/")
async def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, str | bool]:
    return {"status": "ok", "groq_configured": bool(os.getenv("GROQ_API_KEY"))}


@app.post("/api/process")
async def process_image(file: UploadFile = File(...)) -> dict[str, object]:
    if file.content_type not in {"image/png", "image/jpeg", "image/webp", "image/tiff"}:
        raise HTTPException(status_code=415, detail="Upload a PNG, JPG, WEBP, or TIFF image.")

    image_bytes = await file.read(MAX_IMAGE_BYTES + 1)
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Images must be smaller than 12 MB.")

    return index_image(image_bytes, file.filename or "image")


@app.post("/api/ask")
async def ask_question(request: QuestionRequest) -> dict[str, object]:
    return answer_image_question(request.image_id, request.question)