import os

from openai import AzureOpenAI

from app.config import load_environment

load_environment()


def is_openai_configured() -> bool:
    return all(
        [
            os.getenv("AZURE_OPENAI_ENDPOINT"),
            os.getenv("AZURE_OPENAI_API_KEY"),
            os.getenv("AZURE_OPENAI_API_VERSION"),
            os.getenv("AZURE_OPENAI_DEPLOYMENT"),
        ]
    )


def _build_client() -> AzureOpenAI:
    return AzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    )


def ask_azure_openai(
    message: str, system_prompt: str | None = None, max_completion_tokens: int = 300
) -> str:
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    client = _build_client()
    messages = []

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": message})

    response = client.chat.completions.create(
        model=deployment,
        messages=messages,
        max_completion_tokens=max_completion_tokens,
    )

    return response.choices[0].message.content or ""


def safe_ask_azure_openai(
    message: str,
    system_prompt: str | None = None,
    max_completion_tokens: int = 300,
) -> str | None:
    if not is_openai_configured():
        return None

    try:
        return ask_azure_openai(
            message=message,
            system_prompt=system_prompt,
            max_completion_tokens=max_completion_tokens,
        )
    except Exception as error:
        return f"Azure OpenAI no disponible: {error}"
