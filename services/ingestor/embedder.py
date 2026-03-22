import structlog
from openai import AsyncOpenAI, BadRequestError

log = structlog.get_logger()

MAX_TEXTS_PER_BATCH = 2000  # OpenAI item limit
MAX_ESTIMATED_TOKENS = 240000  # Stay well below the 300k request ceiling


def _estimate_tokens(text: str) -> int:
    """Conservative token estimate for batching without tiktoken."""
    return max(1, len(text) // 4)


class Embedder:
    def __init__(self, api_key: str, model: str = "text-embedding-3-small", dimensions: int = 384):
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self._dimensions = dimensions

    async def _embed_request(self, texts: list[str]) -> list[list[float]]:
        try:
            response = await self._client.embeddings.create(
                input=texts,
                model=self._model,
                dimensions=self._dimensions,
            )
        except BadRequestError as exc:
            if "max_tokens_per_request" not in str(exc) or len(texts) == 1:
                raise

            midpoint = max(1, len(texts) // 2)
            log.warning(
                "embeddings_split_batch",
                batch_size=len(texts),
                left=midpoint,
                right=len(texts) - midpoint,
            )
            left = await self._embed_request(texts[:midpoint])
            right = await self._embed_request(texts[midpoint:])
            return left + right

        return [item.embedding for item in response.data]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        all_embeddings = []
        offset = 0

        while offset < len(texts):
            batch = []
            estimated_tokens = 0

            while offset < len(texts) and len(batch) < MAX_TEXTS_PER_BATCH:
                text = texts[offset]
                text_tokens = _estimate_tokens(text)
                if batch and estimated_tokens + text_tokens > MAX_ESTIMATED_TOKENS:
                    break
                batch.append(text)
                estimated_tokens += text_tokens
                offset += 1

            batch_embeddings = await self._embed_request(batch)
            all_embeddings.extend(batch_embeddings)

            log.info(
                "embeddings_batch",
                offset=offset - len(batch),
                batch_size=len(batch),
                estimated_tokens=estimated_tokens,
            )

        return all_embeddings
