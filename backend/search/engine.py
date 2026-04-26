"""
Hybrid search engine combining:
1. BM25-style keyword search (TF-IDF via scikit-learn)
2. Semantic search (sentence-transformers + FAISS)
3. Hybrid mode (weighted combination of both)
"""

import logging
import math
import os
import pickle
from pathlib import Path

import faiss
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sentence_transformers import SentenceTransformer

from sqlalchemy.orm import Session
from backend.models.schemas import Page

logger = logging.getLogger(__name__)

INDEX_DIR = Path("./data/index")
INDEX_DIR.mkdir(parents=True, exist_ok=True)

# Global singletons (loaded once per process)
_embedding_model = None


def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        logger.info("Loading sentence-transformer model...")
        # Force CPU. macOS MPS (GPU) breaks inside Celery's prefork workers
        # because the Metal compiler service handle doesn't survive fork().
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
    return _embedding_model


class SearchEngine:
    """Handles indexing and searching over crawled pages."""

    def __init__(self, db: Session):
        self.db = db
        self.tfidf_path = INDEX_DIR / "tfidf.pkl"
        self.faiss_path = INDEX_DIR / "faiss.index"
        self.meta_path = INDEX_DIR / "meta.pkl"

    def build_index(self):
        """Build both TF-IDF and FAISS indices from all pages in DB."""
        pages = self.db.query(Page).filter(Page.status == "crawled").all()
        if not pages:
            logger.warning("No pages to index")
            return

        logger.info(f"Building index for {len(pages)} pages...")

        # Prepare documents
        docs = []
        metadata = []
        for p in pages:
            text = f"{p.title} {p.content[:5000]}"
            docs.append(text)
            metadata.append({
                "id": p.id,
                "url": p.url,
                "title": p.title,
                "snippet": p.content[:300],
            })

        # 1. Build TF-IDF index
        tfidf = TfidfVectorizer(
            max_features=20000,
            stop_words="english",
            ngram_range=(1, 2),
            sublinear_tf=True,
        )
        tfidf_matrix = tfidf.fit_transform(docs)

        with open(self.tfidf_path, "wb") as f:
            pickle.dump({"vectorizer": tfidf, "matrix": tfidf_matrix}, f)

        # 2. Build FAISS semantic index
        model = get_embedding_model()
        embeddings = model.encode(
            [d[:512] for d in docs],  # Truncate for embedding
            show_progress_bar=True,
            batch_size=32,
            normalize_embeddings=True,
        )
        embeddings = np.array(embeddings, dtype="float32")

        dim = embeddings.shape[1]
        index = faiss.IndexFlatIP(dim)  # Inner product (cosine sim since normalized)
        index.add(embeddings)
        faiss.write_index(index, str(self.faiss_path))

        # Save metadata
        with open(self.meta_path, "wb") as f:
            pickle.dump(metadata, f)

        logger.info(f"Index built: {len(docs)} documents")

    def search_keyword(self, query: str, top_k: int = 20) -> list[dict]:
        """TF-IDF keyword search."""
        if not self.tfidf_path.exists() or not self.meta_path.exists():
            return []

        with open(self.tfidf_path, "rb") as f:
            data = pickle.load(f)
        with open(self.meta_path, "rb") as f:
            metadata = pickle.load(f)

        vectorizer = data["vectorizer"]
        matrix = data["matrix"]

        query_vec = vectorizer.transform([query])
        scores = (matrix @ query_vec.T).toarray().flatten()

        top_indices = np.argsort(scores)[::-1][:top_k]
        results = []
        for idx in top_indices:
            if scores[idx] > 0:
                results.append({
                    **metadata[idx],
                    "score": float(scores[idx]),
                })
        return results

    def search_semantic(self, query: str, top_k: int = 20) -> list[dict]:
        """FAISS semantic search using sentence embeddings."""
        if not self.faiss_path.exists() or not self.meta_path.exists():
            return []

        with open(self.meta_path, "rb") as f:
            metadata = pickle.load(f)

        model = get_embedding_model()
        query_embedding = model.encode([query], normalize_embeddings=True)
        query_embedding = np.array(query_embedding, dtype="float32")

        index = faiss.read_index(str(self.faiss_path))
        scores, indices = index.search(query_embedding, min(top_k, index.ntotal))

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx >= 0 and score > 0:
                results.append({
                    **metadata[idx],
                    "score": float(score),
                })
        return results

    def search_hybrid(self, query: str, top_k: int = 20, keyword_weight: float = 0.3) -> list[dict]:
        """
        Hybrid search: combine keyword and semantic scores with reciprocal rank fusion.
        """
        keyword_results = self.search_keyword(query, top_k=top_k * 2)
        semantic_results = self.search_semantic(query, top_k=top_k * 2)

        # Reciprocal Rank Fusion
        k = 60  # RRF constant
        rrf_scores = {}
        url_data = {}

        for rank, r in enumerate(keyword_results):
            url = r["url"]
            rrf_scores[url] = rrf_scores.get(url, 0) + keyword_weight / (k + rank + 1)
            url_data[url] = r

        for rank, r in enumerate(semantic_results):
            url = r["url"]
            rrf_scores[url] = rrf_scores.get(url, 0) + (1 - keyword_weight) / (k + rank + 1)
            if url not in url_data:
                url_data[url] = r

        sorted_urls = sorted(rrf_scores, key=rrf_scores.get, reverse=True)[:top_k]
        results = []
        for url in sorted_urls:
            data = url_data[url]
            data["score"] = rrf_scores[url]
            results.append(data)

        return results

    def search(self, query: str, mode: str = "hybrid", top_k: int = 20) -> list[dict]:
        """Dispatch search to the appropriate mode."""
        if mode == "keyword":
            return self.search_keyword(query, top_k)
        elif mode == "semantic":
            return self.search_semantic(query, top_k)
        else:
            return self.search_hybrid(query, top_k)
