"""The bot's only knowledge retrieval backend: the versioned RAG Service API."""
import httpx # type: ignore


class RemoteKnowledgeSearch:
    def __init__(self, base_url: str, api_key: str, timeout: float = 40):
        self.client = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout, connect=5),
            follow_redirects=False,
        )

    def search(self, question: str, *, categories: list[str] | None = None):
        response = self.client.post("api/v1/knowledge/search", json={"query": question, "categories": categories})
        # A timeout/503 is NOT knowledge_not_found. Let the bot handle service failure separately.
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not all(key in data for key in ("success", "status", "content", "sources")):
            raise ValueError("RAG service response không đúng hợp đồng API")
        if (
            not isinstance(data["success"], bool)
            or not isinstance(data["status"], str)
            or not isinstance(data["content"], str)
            or not isinstance(data["sources"], list)
            or not all(isinstance(source, dict) for source in data["sources"])
            or data["status"] not in {"knowledge_found", "knowledge_not_found"}
            or data["success"] != (data["status"] == "knowledge_found")
            or (data["success"] and not data["content"].strip())
            or (not data["success"] and (data["content"] or data["sources"]))
        ):
            raise ValueError("RAG service response không đúng hợp đồng API")
        return data

    def close(self):
        self.client.close()
