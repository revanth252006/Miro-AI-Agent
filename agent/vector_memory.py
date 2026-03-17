# -*- coding: utf-8 -*-
"""
Miro Vector Memory — F10: ChromaDB-based semantic memory system.
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
        """One-time import of brain.json facts into vector store.
        F10 FIX: handles both encrypted and unencrypted brain.json,
        and the actual profile.facts structure (list of {key, value} objects)."""
        if not self.collection or not os.path.exists(BRAIN_JSON):
            return
        
        try:
            with open(BRAIN_JSON, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            
            # Skip if encrypted (starts with gAAAAA or similar Fernet token)
            if content.startswith('gAAAA') or not content.startswith('{'):
                print("⚠️ brain.json appears encrypted — skipping vector import (will import after decryption)")
                return
            
            data = json.loads(content)
            
            # Extract facts from multiple possible locations
            facts_to_import = []
            
            # Format 1: data.facts = ["fact1", "fact2", ...]
            if isinstance(data.get("facts"), list):
                for f in data["facts"]:
                    if isinstance(f, str):
                        facts_to_import.append(f)
                    elif isinstance(f, dict):
                        # Format 2: data.facts = [{"key": "name", "value": "Revanth"}, ...]
                        k = f.get("key", f.get("category", ""))
                        v = f.get("value", f.get("detail", ""))
                        if k and v:
                            facts_to_import.append(f"User's {k}: {v}")
            
            # Format 3: data.profile.facts
            profile = data.get("profile", {})
            if isinstance(profile.get("facts"), list):
                for f in profile["facts"]:
                    if isinstance(f, str):
                        facts_to_import.append(f)
                    elif isinstance(f, dict):
                        k = f.get("key", f.get("category", ""))
                        v = f.get("value", f.get("detail", ""))
                        if k and v:
                            facts_to_import.append(f"User's {k}: {v}")
            
            # Format 4: data.profile.preferences
            if isinstance(profile.get("preferences"), dict):
                for k, v in profile["preferences"].items():
                    facts_to_import.append(f"User prefers {k}: {v}")
            
            # Format 5: data.profile direct fields
            if profile.get("name"):
                facts_to_import.append(f"User's name is {profile['name']}")
            if profile.get("location"):
                facts_to_import.append(f"User lives in {profile['location']}")
            
            if not facts_to_import:
                return
            
            # Check if already imported
            if self.collection.count() >= len(facts_to_import):
                return
            
            # Deduplicate
            facts_to_import = list(set(facts_to_import))
            
            ids = [f"brain_fact_{i}" for i in range(len(facts_to_import))]
            metadatas = [{"source": "brain.json", "imported": True, "timestamp": datetime.now().isoformat()} for _ in facts_to_import]
            
            self.collection.upsert(
                ids=ids,
                documents=facts_to_import,
                metadatas=metadatas
            )
            print(f"📥 Imported {len(facts_to_import)} facts from brain.json into vector memory")
        except Exception as e:
            print(f"⚠️ brain.json import failed: {e}")

    async def store(self, text: str, metadata: dict = None):
        """Store a memory with semantic embedding.
        F10: Adds timestamp, emotion, and topic metadata."""
        if not self.collection or not text or len(text.strip()) < 5:
            return
        
        mem_id = f"mem_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{hash(text) % 10000}"
        meta = metadata or {}
        meta["timestamp"] = datetime.now().isoformat()
        if "source" not in meta:
            meta["source"] = "conversation"
        
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: self.collection.add(
                ids=[mem_id],
                documents=[text],
                metadatas=[meta]
            ))
        except Exception as e:
            # ChromaDB may reject duplicates — that's fine
            if "already exists" not in str(e).lower():
                print(f"⚠️ Vector store error: {e}")

    async def recall(self, query: str, n_results: int = 5) -> list[str]:
        """Recall relevant memories based on semantic similarity."""
        if not self.collection or self.collection.count() == 0:
            return []
        
        try:
            loop = asyncio.get_running_loop()
            results = await loop.run_in_executor(None, lambda: self.collection.query(
                query_texts=[query],
                n_results=min(n_results, self.collection.count())
            ))
            
            if results and results['documents']:
                return results['documents'][0]
        except Exception as e:
            print(f"⚠️ Vector recall error: {e}")
        return []

    async def recall_formatted(self, query: str, n_results: int = 5) -> str:
        """Recall and format memories for injection into prompt."""
        memories = await self.recall(query, n_results)
        if not memories:
            return ""
        
        lines = ["[RELEVANT MEMORIES FROM PAST CONVERSATIONS]:"]
        for i, mem in enumerate(memories, 1):
            # Truncate very long memories
            if len(mem) > 200:
                mem = mem[:200] + "..."
            lines.append(f"  {i}. {mem}")
        lines.append("[END MEMORIES]")
        return "\n".join(lines)

    def count(self) -> int:
        """Returns total stored memories."""
        if not self.collection:
            return 0
        return self.collection.count()
