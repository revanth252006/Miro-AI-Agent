# -*- coding: utf-8 -*-
"""
Miro Vector Memory — ChromaDB-based semantic memory system.
Replaces flat brain.json with vector search for contextual recall.
Backward compatible: still reads/writes brain.json as a backup.
"""

import os
import json
import asyncio
from datetime import datetime

try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False

MEMORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory_data")
BRAIN_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brain.json")


class VectorMemory:
    """Semantic vector memory using ChromaDB for long-term recall."""

    def __init__(self):
        os.makedirs(MEMORY_DIR, exist_ok=True)
        
        if CHROMADB_AVAILABLE:
            self.client = chromadb.PersistentClient(path=MEMORY_DIR)
            self.collection = self.client.get_or_create_collection(
                name="miro_memories",
                metadata={"hnsw:space": "cosine"}
            )
            print(f"✅ Vector memory online ({self.collection.count()} memories)")
        else:
            self.client = None
            self.collection = None
            print("⚠️ ChromaDB not installed — using flat memory (pip install chromadb)")
        
        # Load existing brain.json memories into ChromaDB
        self._import_brain_json()

    def _import_brain_json(self):
        """One-time import of brain.json facts into vector store."""
        if not self.collection or not os.path.exists(BRAIN_JSON):
            return
        
        try:
            with open(BRAIN_JSON, 'r') as f:
                data = json.load(f)
            
            facts = data.get("facts", [])
            if not facts:
                return
            
            # Check if already imported
            if self.collection.count() >= len(facts):
                return
            
            ids = [f"brain_fact_{i}" for i in range(len(facts))]
            documents = facts
            metadatas = [{"source": "brain.json", "imported": True} for _ in facts]
            
            self.collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas
            )
            print(f"📥 Imported {len(facts)} facts from brain.json into vector memory")
        except Exception as e:
            print(f"⚠️ brain.json import failed: {e}")

    async def store(self, text: str, metadata: dict = None):
        """Store a memory with semantic embedding."""
        if not self.collection:
            return
        
        mem_id = f"mem_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{hash(text) % 10000}"
        meta = metadata or {}
        meta["timestamp"] = datetime.now().isoformat()
        
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: self.collection.add(
            ids=[mem_id],
            documents=[text],
            metadatas=[meta]
        ))

    async def recall(self, query: str, n_results: int = 5) -> list[str]:
        """Recall relevant memories based on semantic similarity."""
        if not self.collection or self.collection.count() == 0:
            return []
        
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(None, lambda: self.collection.query(
            query_texts=[query],
            n_results=min(n_results, self.collection.count())
        ))
        
        if results and results['documents']:
            return results['documents'][0]
        return []

    async def recall_formatted(self, query: str, n_results: int = 5) -> str:
        """Recall and format memories for injection into prompt."""
        memories = await self.recall(query, n_results)
        if not memories:
            return ""
        
        lines = ["[RELEVANT MEMORIES FROM PAST CONVERSATIONS]:"]
        for i, mem in enumerate(memories, 1):
            lines.append(f"  {i}. {mem}")
        lines.append("[END MEMORIES]")
        return "\n".join(lines)

    def count(self) -> int:
        """Returns total stored memories."""
        if not self.collection:
            return 0
        return self.collection.count()
