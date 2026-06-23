import os, re, hashlib
from typing import List, Dict
from pathlib import Path
from . import console

class CodebaseMemory:
    def __init__(self, workspace_dir: str):
        self.workspace_dir = workspace_dir; self.db_path = os.path.join(workspace_dir, ".samcode", "vector_db")
        os.makedirs(self.db_path, exist_ok=True); self._is_indexed = False; self.model = None; self.collection = None
        self._file_hashes = {}
        try:
            import chromadb; from sentence_transformers import SentenceTransformer
            self.client = chromadb.PersistentClient(path=self.db_path)
            self.collection = self.client.get_or_create_collection(name="codebase", metadata={"hnsw:space": "cosine"})
            self.model = SentenceTransformer('all-MiniLM-L6-v2')
        except Exception as e: console.print(f"[yellow]⚠️ Vector memory unavailable. Run: pip install 'numpy<2' torch transformers sentence-transformers[/yellow]")

    def _get_file_hash(self, filepath: str) -> str:
        try:
            with open(filepath, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except:
            return str(hash(filepath))

    def index_workspace(self, file_manager):
        if self._is_indexed or not self.model: return
        console.print("[cyan]🧠 Building vector memory index...[/cyan]")
        files = file_manager.scan_workspace(max_files=500); docs, ids, metadatas = [], [], []
        code_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.go', '.rs', '.html', '.css', '.scss', '.sql', '.sh'}
        for f in files:
            if Path(f).suffix.lower() in code_extensions:
                content = file_manager.read_file(f)
                if content:
                    file_hash = self._get_file_hash(str(Path(self.workspace_dir) / f))
                    if file_hash in self._file_hashes:
                        continue
                    lines = content.split('\n')
                    if len(lines) <= 300:
                        docs.append(f"File: {f}\n{content}")
                    else:
                        docs.append(f"File: {f}\n" + '\n'.join(lines[:150]) + f"\n... [truncated, {len(lines)} total lines]")
                    safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', f.replace(os.sep, "_"))
                    if not safe_id: safe_id = f"file_{len(ids)}"
                    ids.append(safe_id)
                    metadatas.append({"file": f, "ext": Path(f).suffix.lower(), "hash": file_hash})
                    self._file_hashes[file_hash] = True
        if docs:
            chunk_size = 50
            for i in range(0, len(docs), chunk_size):
                chunk_docs = docs[i:i + chunk_size]
                chunk_ids = ids[i:i + chunk_size]
                chunk_metadatas = metadatas[i:i + chunk_size]
                embeddings = self.model.encode(chunk_docs, show_progress_bar=False).tolist()
                self.collection.upsert(documents=chunk_docs, embeddings=embeddings, ids=chunk_ids, metadatas=chunk_metadatas)
            console.print(f"[green]✓ Indexed {len(docs)} files into vector memory.[/green]")
        self._is_indexed = True

    def search(self, query: str, n_results: int = 5) -> List[Dict]:
        if not self.model: return []
        query_embedding = self.model.encode([query]).tolist()
        results = self.collection.query(query_embeddings=query_embedding, n_results=n_results)
        out = []
        for m, d in zip(results["metadatas"][0], results["documents"][0]):
            snippet = d[:300].replace('\n', ' ') + "..." if len(d) > 300 else d.replace('\n', ' ')
            out.append({"file": m["file"], "snippet": snippet})
        return out