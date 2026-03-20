import structlog
from openai import AsyncOpenAI

log = structlog.get_logger()

BATCH_SIZE = 2000  # OpenAI batch limit


class Embedder:
    def __init__(self, api_key: str, model: str = "text-embedding-3-small", dimensions: int = 384):
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self._dimensions = dimensions

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        all_embeddings = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i : i + BATCH_SIZE]
            response = await self._client.embeddings.create(
                input=batch,
                model=self._model,
                dimensions=self._dimensions,
            )
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)
            log.info("embeddings_batch", offset=i, batch_size=len(batch))
        return all_embeddings
