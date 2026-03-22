import { H1, H2, P, Code, CodeBlock, Table, Callout, UL } from "../../components/Prose.tsx";

export default function EmbeddingsPgvector() {
  return (
    <>
      <H1>Embeddings & pgvector</H1>

      <P>
        With thousands of active markets, finding logically related pairs is a needle-in-a-haystack
        problem. PolyArb uses semantic embeddings and vector similarity search to efficiently
        narrow the search space.
      </P>

      <H2>How Embeddings Work</H2>

      <P>
        Each market's question text (e.g., "Will Bitcoin exceed $100k by December 2024?") is
        converted into a 384-dimensional vector using OpenAI's <Code>text-embedding-3-small</Code> model.
        Markets with similar questions will have vectors that are close together in this
        high-dimensional space.
      </P>

      <CodeBlock lang="python">{`# Embedding a market question
response = openai_client.embeddings.create(
    model="text-embedding-3-small",
    input="Will Bitcoin exceed $100k by December 2024?",
    dimensions=384,
)
embedding = response.data[0].embedding  # 384-dim float vector`}</CodeBlock>

      <H2>pgvector Storage</H2>

      <P>
        Embeddings are stored in the <Code>markets</Code> table using PostgreSQL's pgvector
        extension. The <Code>embedding</Code> column is of type <Code>Vector(384)</Code>, which
        enables efficient similarity search using vector indexes.
      </P>

      <CodeBlock lang="sql">{`-- The markets table has a pgvector column
CREATE TABLE markets (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    embedding vector(384),
    ...
);`}</CodeBlock>

      <H2>Similarity Search</H2>

      <P>
        The detector queries pgvector to find the top-K most similar markets for each market
        being analyzed. This uses cosine distance (<Code>{"<=>"}</Code> operator):
      </P>

      <Table
        headers={["Parameter", "Value"]}
        rows={[
          ["Model", <Code>text-embedding-3-small</Code>],
          ["Dimensions", "384"],
          ["Similarity threshold", <Code>0.82</Code>],
          ["Top-K per market", <Code>20</Code>],
          ["Batch size", <Code>100</Code>],
        ]}
      />

      <P>
        Markets with cosine similarity above <Code>0.82</Code> are considered candidate pairs
        and passed to the LLM classifier for dependency type classification.
      </P>

      <H2>Why 384 Dimensions?</H2>

      <P>
        OpenAI's <Code>text-embedding-3-small</Code> supports dimension reduction via the
        <Code>dimensions</Code> parameter. 384 dimensions provides a good balance between accuracy
        and storage/query performance. The full model outputs 1536 dimensions, but 384 retains
        most of the semantic information at 1/4 the storage cost.
      </P>

      <Callout type="tip">
        Embedding generation happens in the ingestor service when new markets are discovered.
        The detector only queries existing embeddings — it doesn't generate new ones.
      </Callout>

      <H2>Performance Considerations</H2>

      <UL>
        <li>pgvector uses IVFFlat or HNSW indexes for approximate nearest-neighbor search</li>
        <li>With thousands of markets, a full similarity scan takes milliseconds</li>
        <li>Embeddings are generated once per market and cached in the database</li>
        <li>The <Code>similarity_top_k = 20</Code> limit prevents the classifier from being overwhelmed</li>
      </UL>
    </>
  );
}
