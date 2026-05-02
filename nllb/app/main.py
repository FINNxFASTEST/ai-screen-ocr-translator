import os
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from transformers import pipeline, AutoTokenizer, AutoModelForSeq2SeqLM
import torch

from languages import NLLB_LANGUAGES
from v1_router import router as v1_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_ID = os.getenv("MODEL_ID", "facebook/nllb-200-1.3B")
DEVICE = os.getenv("DEVICE", "cpu")  # set to "cuda" if GPU available
MAX_LENGTH = int(os.getenv("MAX_LENGTH", "512"))

translator = None
tokenizer = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global translator, tokenizer
    logger.info(f"Loading model: {MODEL_ID} on device: {DEVICE}")
    device = 0 if DEVICE == "cuda" and torch.cuda.is_available() else -1
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_ID)
    translator = pipeline(
        "translation",
        model=model,
        tokenizer=tokenizer,
        device=device,
    )
    logger.info("Model loaded successfully")
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="NLLB-200 Translation API",
    description="Local translation service powered by Meta's NLLB-200 1.3B model",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(v1_router)


class TranslateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    source_lang: str = Field(..., example="eng_Latn")
    target_lang: str = Field(..., example="tha_Thai")
    max_length: Optional[int] = Field(None, ge=1, le=2048)


class TranslateResponse(BaseModel):
    translated_text: str
    source_lang: str
    target_lang: str
    model: str


class BatchTranslateRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=50)
    source_lang: str
    target_lang: str
    max_length: Optional[int] = Field(None, ge=1, le=2048)


class BatchTranslateResponse(BaseModel):
    translations: list[str]
    source_lang: str
    target_lang: str
    model: str


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_ID, "device": DEVICE}


@app.get("/languages")
def list_languages():
    return {"languages": NLLB_LANGUAGES}


@app.post("/translate", response_model=TranslateResponse)
def translate(req: TranslateRequest):
    if req.source_lang not in NLLB_LANGUAGES:
        raise HTTPException(400, f"Unknown source_lang '{req.source_lang}'. GET /languages for valid codes.")
    if req.target_lang not in NLLB_LANGUAGES:
        raise HTTPException(400, f"Unknown target_lang '{req.target_lang}'. GET /languages for valid codes.")
    if translator is None:
        raise HTTPException(503, "Model not ready")

    max_len = req.max_length or MAX_LENGTH
    try:
        result = translator(
            req.text,
            src_lang=req.source_lang,
            tgt_lang=req.target_lang,
            max_length=max_len,
        )
        return TranslateResponse(
            translated_text=result[0]["translation_text"],
            source_lang=req.source_lang,
            target_lang=req.target_lang,
            model=MODEL_ID,
        )
    except Exception as e:
        logger.error(f"Translation error: {e}")
        raise HTTPException(500, str(e))


@app.post("/translate/batch", response_model=BatchTranslateResponse)
def translate_batch(req: BatchTranslateRequest):
    if req.source_lang not in NLLB_LANGUAGES:
        raise HTTPException(400, f"Unknown source_lang '{req.source_lang}'.")
    if req.target_lang not in NLLB_LANGUAGES:
        raise HTTPException(400, f"Unknown target_lang '{req.target_lang}'.")
    if translator is None:
        raise HTTPException(503, "Model not ready")

    max_len = req.max_length or MAX_LENGTH
    try:
        results = translator(
            req.texts,
            src_lang=req.source_lang,
            tgt_lang=req.target_lang,
            max_length=max_len,
        )
        return BatchTranslateResponse(
            translations=[r["translation_text"] for r in results],
            source_lang=req.source_lang,
            target_lang=req.target_lang,
            model=MODEL_ID,
        )
    except Exception as e:
        logger.error(f"Batch translation error: {e}")
        raise HTTPException(500, str(e))
