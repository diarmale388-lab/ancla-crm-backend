import logging
import httpx
import sqlalchemy as sa
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional

from app.config import settings
from app.models.base import KnowledgeDocument, KnowledgeChunk
from app.services.ai_engine import ai_engine

logger = logging.getLogger("rag_service")

def chunk_text(text: str, chunk_size: int = 800, overlap: int = 150) -> List[str]:
    """
    Segmenta el texto en fragmentos de unos 'chunk_size' caracteres con un solape de 'overlap'.
    Intenta no cortar palabras a la mitad.
    """
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text.strip()]
        
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end < len(text):
            # Intentar retroceder hasta el último espacio para no cortar palabra
            last_space = text.rfind(" ", start, end)
            if last_space != -1 and last_space > start + (chunk_size // 2):
                end = last_space
        
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        
        start = end - overlap
        # Evitar loops infinitos o fragmentos minúsculos al final
        if start >= len(text) - overlap:
            last_chunk = text[end - overlap:].strip()
            if last_chunk and len(last_chunk) > 20:
                chunks.append(last_chunk)
            break
            
    return chunks


async def generate_embedding(text: str, db: Session = None) -> Optional[List[float]]:
    """
    Genera el embedding vectorial de 768 dimensiones para el texto dado usando Gemini text-embedding-004.
    """
    # Intentar obtener la clave API
    api_key = None
    if db:
        try:
            from app.models.base import SystemSetting
            db_key = db.query(SystemSetting).filter(SystemSetting.key == "gemini_api_key").first()
            if db_key and db_key.value:
                api_key = db_key.value
        except Exception:
            pass
            
    if not api_key:
        api_key = settings.GEMINI_API_KEY
        
    if not api_key:
        logger.error("No se pudo obtener una clave API para generar embeddings.")
        return None

    # Si es clave de OpenRouter, llamar a su API de embeddings
    if api_key.startswith("sk-or-v1"):
        url = "https://openrouter.ai/api/v1/embeddings"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "openai/text-embedding-3-small",
            "input": text,
            "dimensions": 768
        }
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(url, headers=headers, json=payload, timeout=10.0)
                if res.status_code == 200:
                    data = res.json()
                    return data["data"][0]["embedding"]
                else:
                    logger.error(f"Error llamando a OpenRouter Embeddings (status {res.status_code}): {res.text}")
                    return None
        except Exception as e:
            logger.error(f"Excepción llamando a OpenRouter Embeddings: {e}")
            return None

    # Endpoint oficial de Gemini Embeddings (v1beta)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key={api_key}"
    payload = {
        "model": "models/text-embedding-004",
        "content": {
            "parts": [
                {"text": text}
            ]
        }
    }

    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(url, json=payload, timeout=10.0)
            if res.status_code == 200:
                data = res.json()
                return data.get("embedding", {}).get("values")
            else:
                logger.error(f"Error llamando a Gemini Embeddings API (status {res.status_code}): {res.text}")
                return None
    except Exception as e:
        logger.error(f"Excepción llamando a Gemini Embeddings: {e}")
        return None


async def index_document(db: Session, doc: KnowledgeDocument) -> bool:
    """
    Segmenta un documento en fragmentos, genera sus embeddings vectoriales
    y los persiste en la base de datos Neon PostgreSQL.
    """
    logger.info(f"Iniciando indexación vectorial del documento ID {doc.id} ({doc.filename})...")
    try:
        # 1. Eliminar chunks previos si ya existían para este documento (re-indexación)
        db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == doc.id).delete()
        db.commit()

        # 2. Fragmentar el texto
        chunks_text = chunk_text(doc.extracted_text)
        if not chunks_text:
            logger.warning(f"El documento ID {doc.id} no extrajo ningún fragmento de texto.")
            return False

        logger.info(f"Documento segmentado en {len(chunks_text)} fragmentos. Generando embeddings...")

        # 3. Generar embeddings y persistir
        chunks_added = 0
        for i, text in enumerate(chunks_text):
            embedding = await generate_embedding(text, db)
            if not embedding:
                logger.error(f"No se pudo generar embedding para fragmento {i+1}/{len(chunks_text)}. Omitiendo.")
                continue

            chunk = KnowledgeChunk(
                document_id=doc.id,
                content=text,
                embedding=embedding
            )
            db.add(chunk)
            chunks_added += 1

        db.commit()
        logger.info(f"Indexación vectorial completada con éxito. Se insertaron {chunks_added} chunks para el documento ID {doc.id}.")
        return chunks_added > 0
    except Exception as e:
        logger.error(f"Error durante la indexación del documento ID {doc.id}: {e}")
        db.rollback()
        return False


async def search_hybrid_knowledge(query: str, db: Session, limit: int = 4) -> List[str]:
    """
    Realiza una búsqueda híbrida combinando pgvector y búsqueda de texto léxica en Postgres.
    Fusiona ambos rankings usando Reciprocal Rank Fusion (RRF) para retornar los top fragmentos.
    """
    if not query.strip():
        return []

    # 1. Generar embedding de la consulta
    query_embedding = await generate_embedding(query, db)
    
    semantic_chunks = []
    if query_embedding:
        try:
            # Búsqueda semántica usando pgvector (distancia coseno)
            semantic_chunks = db.query(KnowledgeChunk)\
                .order_by(KnowledgeChunk.embedding.cosine_distance(query_embedding))\
                .limit(limit * 3)\
                .all()
        except Exception as ve:
            logger.error(f"Error en consulta semántica pgvector: {ve}")

    # 2. Búsqueda léxica (palabras clave nativas de Postgres)
    lexical_chunks = []
    try:
        # plainto_tsquery procesa texto de búsqueda y lo convierte a formato léxico compatible.
        # Usamos el operador op('@@') para evitar que match() duplique la función plainto_tsquery
        lexical_chunks = db.query(KnowledgeChunk)\
            .filter(sa.func.to_tsvector('spanish', KnowledgeChunk.content).op('@@')(sa.func.plainto_tsquery('spanish', query)))\
            .order_by(sa.desc(sa.func.ts_rank_cd(sa.func.to_tsvector('spanish', KnowledgeChunk.content), sa.func.plainto_tsquery('spanish', query))))\
            .limit(limit * 3)\
            .all()
    except Exception as le:
        logger.error(f"Error en consulta léxica tsvector: {le}")

    # 3. Reciprocal Rank Fusion (RRF)
    # RRF_Score = 0.7 / (60 + rank_semantic) + 0.3 / (60 + rank_lexical)
    rrf_scores = {}
    
    # Mapear chunks de vuelta a objetos
    chunk_map = {}

    # Rankear semántico
    for rank, chunk in enumerate(semantic_chunks):
        chunk_map[chunk.id] = chunk
        # rank es 0-indexed, así que rank+1 es el ranking real (1-indexed)
        rrf_scores[chunk.id] = rrf_scores.get(chunk.id, 0.0) + (0.7 / (60.0 + (rank + 1)))

    # Rankear léxico
    for rank, chunk in enumerate(lexical_chunks):
        chunk_map[chunk.id] = chunk
        rrf_scores[chunk.id] = rrf_scores.get(chunk.id, 0.0) + (0.3 / (60.0 + (rank + 1)))

    # Si no hay coincidencias de base, intentar retornar por similitud coseno si existió
    if not rrf_scores and semantic_chunks:
        return [c.content for c in semantic_chunks[:limit]]

    # Ordenar por puntuación RRF de forma descendente
    sorted_chunk_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)
    
    top_chunks = [chunk_map[cid].content for cid in sorted_chunk_ids[:limit]]
    logger.info(f"Búsqueda híbrida completada. Chunks recuperados: {len(top_chunks)} (query: '{query}')")
    return top_chunks
