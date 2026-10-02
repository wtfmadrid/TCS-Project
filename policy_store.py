import argparse
import hashlib
import json
from functools import lru_cache
from pathlib import Path

import chromadb
import pymupdf
from dotenv import load_dotenv
from langchain_huggingface import HuggingFaceEmbeddings
from transformers import AutoTokenizer
from langchain_text_splitters import RecursiveCharacterTextSplitter


BASE_DIR = Path(__file__).resolve().parent
CHROMA_PATH = BASE_DIR / "data" / "chroma"
COLLECTION_NAME = "policy_chunks_minilm_v1"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_CACHE = BASE_DIR / "data" / "models"

load_dotenv(BASE_DIR / ".env", override=True)


@lru_cache(maxsize=1)
def get_collection():
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))

    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=None,
        metadata={"hnsw:space": "cosine"},
    )


@lru_cache(maxsize=1)
def get_embeddings():
    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        cache_folder=str(MODEL_CACHE),
        model_kwargs={"device": "cpu"},
        encode_kwargs={
            "normalize_embeddings": True,
            "batch_size": 16,
        },
        show_progress=False,
    )


def ingest_pdf(
    file_path: str,
    company: str,
    version: str,
) -> dict:
    path = Path(file_path).resolve()

    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise ValueError("Provide the path to an existing PDF.")

    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("Please use a PDF smaller than 10 MB.")

    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    collection = get_collection()

    # Identical PDF content is indexed only once.
    existing = collection.get(
        where={"document_id": file_hash},
        include=["metadatas"],
    )

    if existing["ids"]:
        return {
            "status": "already_indexed",
            "document_id": file_hash,
            "chunks": len(existing["ids"]),
        }
    
    tokenizer = AutoTokenizer.from_pretrained(
        EMBEDDING_MODEL,
        cache_dir=str(MODEL_CACHE),
    )

    splitter = RecursiveCharacterTextSplitter.from_huggingface_tokenizer(
        tokenizer,
        chunk_size=200,
        chunk_overlap=40,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    texts = []
    metadata = []
    empty_pages = []

    with pymupdf.open(path) as pdf:
        if pdf.needs_pass:
            raise ValueError("Password-protected PDFs are not supported.")

        page_count = len(pdf)

        if page_count > 100:
            raise ValueError("Please use a PDF with 100 pages or fewer.")

        for page_number, page in enumerate(pdf, start=1):
            text = page.get_text("text", sort=True).strip()

            if not text:
                empty_pages.append(page_number)
                continue

            for chunk in splitter.split_text(text):
                texts.append(chunk)
                metadata.append({
                    "document_id": file_hash,
                    "filename": path.name,
                    "page": page_number,
                    "company": company,
                    "version": version,
                })

    if not texts:
        raise ValueError(
            "No readable text found. Use a text-based PDF; OCR is not enabled."
        )

    if len(texts) > 500:
        raise ValueError("This PDF produces too many chunks for this demo.")

    # Compute all embeddings before writing the document.
    vectors = get_embeddings().embed_documents(texts)

    collection.add(
        ids=[f"{file_hash}:{index}" for index in range(len(texts))],
        documents=texts,
        embeddings=vectors,
        metadatas=metadata,
    )

    return {
        "status": "indexed",
        "document_id": file_hash,
        "filename": path.name,
        "pages": page_count,
        "chunks": len(texts),
        "pages_without_text": empty_pages,
    }


def search_policies(query: str, top_k: int = 6) -> dict:
    query = query.strip()

    if not query:
        return {
            "status": "invalid_input",
            "message": "Enter a policy question.",
        }

    if not 1 <= top_k <= 10:
        return {
            "status": "invalid_input",
            "message": "top_k must be between 1 and 10.",
        }

    collection = get_collection()
    count = collection.count()

    if count == 0:
        return {
            "status": "empty",
            "message": "No policy documents have been indexed.",
            "passages": [],
        }

    query_vector = get_embeddings().embed_query(query)

    results = collection.query(
        query_embeddings=[query_vector],
        n_results=min(top_k, count),
        include=["documents", "metadatas", "distances"],
    )

    passages = []

    for chunk_id, text, meta, distance in zip(
        results["ids"][0],
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        passages.append({
            "chunk_id": chunk_id,
            "text": text,
            "filename": meta["filename"],
            "page": meta["page"],
            "company": meta["company"],
            "version": meta["version"],
            "distance": round(float(distance), 4),
        })

    return {
        "status": "success",
        "query": query,
        "passages": passages,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    ingest_command = commands.add_parser("ingest")
    ingest_command.add_argument("file")
    ingest_command.add_argument("--company", required=True)
    ingest_command.add_argument("--version", required=True)

    search_command = commands.add_parser("search")
    search_command.add_argument("query")

    args = parser.parse_args()

    if args.command == "ingest":
        result = ingest_pdf(args.file, args.company, args.version)
    else:
        result = search_policies(args.query)

    print(json.dumps(result, indent=2, ensure_ascii=False))