from openai import AsyncOpenAI

DOCUMENT_CONTEXT_PROMPT = """
<document>
{doc_content}
</document>
""".strip()


CHUNK_CONTEXT_PROMPT = """
Here is the chunk we want to situate within the whole document.
<chunk>
{chunk_content}
</chunk>

Please give a short succinct context to situate this chunk within the overall document for the purposes of improving search retrieval of the chunk.
Answer only with the succinct context and nothing else.
""".strip()


async def situate_chunk_with_openai(
    openai_client: AsyncOpenAI,
    *,
    document_text: str,
    chunk_text: str,
    model: str,
) -> str:
    response = await openai_client.responses.create(
        model=model,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": DOCUMENT_CONTEXT_PROMPT.format(
                            doc_content=document_text
                        ),
                    },
                    {
                        "type": "input_text",
                        "text": CHUNK_CONTEXT_PROMPT.format(chunk_content=chunk_text),
                    },
                ],
            }
        ],
        temperature=0.0,
    )

    output_text = getattr(response, "output_text", "")
    return output_text.strip()
