"""Hugging Face Hub: open a discussion on our own public repo (the "LLM platform").

Docs: https://huggingface.co/docs/hub/en/repositories-pull-requests-discussions
REST endpoint (as used by huggingface_hub.HfApi.create_discussion):
    POST https://huggingface.co/api/{repo_type}s/{repo_id}/discussions
"""

import httpx

from app.platforms.base import BasePlatform, PlatformError, PublishOutcome, secret_value
from app.utils.text import derive_title

HUB_URL = "https://huggingface.co"
_URL_PREFIX = {"model": "", "dataset": "datasets/", "space": "spaces/"}


class HuggingFacePlatform(BasePlatform):
    name = "Hugging Face"
    docs_url = "https://huggingface.co/docs/hub/en/repositories-pull-requests-discussions"

    def is_configured(self) -> bool:
        return bool(self.settings.hf_token and self.settings.hf_repo_id)

    def secrets(self) -> list[str]:
        return [secret_value(self.settings.hf_token)]

    async def publish(self, client: httpx.AsyncClient, message: str, link: str) -> PublishOutcome:
        repo_type = self.settings.hf_repo_type
        repo_id = self.settings.hf_repo_id
        response = await self._request(
            client,
            "POST",
            f"{HUB_URL}/api/{repo_type}s/{repo_id}/discussions",
            headers={"Authorization": f"Bearer {secret_value(self.settings.hf_token)}"},
            json={
                "title": derive_title(message, link),
                "description": message,
                "pullRequest": False,
            },
        )
        data = self.json_body(response)
        num = data.get("num")
        if num is None:
            raise PlatformError("Hugging Face response did not include a discussion number")
        url = f"{HUB_URL}/{_URL_PREFIX[repo_type]}{repo_id}/discussions/{num}"
        return PublishOutcome(url, None, True)
