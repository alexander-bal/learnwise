"""Which provider profile is in use. Kept in memory only (Processing NFR-1, NFR-5)."""

import asyncio
import logging

from app.core.config import ProviderName, ProviderProfile, Settings
from app.llm.adapter import OllamaAdapter

log = logging.getLogger(__name__)


class Providers:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._profiles = settings.profiles()
        self._current: ProviderName = settings.initial_provider
        self._adapters: dict[str, OllamaAdapter] = {}
        self._warmups: set[asyncio.Task[None]] = set()
        self.last_warmup: str | None = None

    @property
    def current(self) -> ProviderProfile:
        return self._profiles[self._current]

    @property
    def profiles(self) -> list[ProviderProfile]:
        return list(self._profiles.values())

    def adapter_for(self, profile: ProviderProfile) -> OllamaAdapter:
        if profile.base_url not in self._adapters:
            self._adapters[profile.base_url] = OllamaAdapter(profile.base_url)
        return self._adapters[profile.base_url]

    def switch(self, name: ProviderName) -> ProviderProfile:
        """Switch profiles. A request in flight keeps the profile it started with."""
        changed = name != self._current
        self._current = name
        if changed:
            log.info("provider switched", extra={"provider": name})
        if changed:
            self.last_warmup = None
        if name == "ollama" and self._settings.keep_model_warm and (changed or not self._warmups):
            self.start_warm_up()
        return self.current

    def start_warm_up(self) -> None:
        profile = self.current
        task = asyncio.create_task(self._warm_up(profile))
        self._warmups.add(task)
        task.add_done_callback(self._warmups.discard)

    async def _warm_up(self, profile: ProviderProfile) -> None:
        # A load request, not a model call: no pool slot, no breaker, no retry, no call log.
        self.last_warmup = "loading"
        try:
            await self.adapter_for(profile).warm_up(
                profile.processing_model, self._settings.processing_num_ctx
            )
        except Exception as exc:
            self.last_warmup = "failed"
            log.warning(
                "model warm-up failed",
                extra={"model": profile.processing_model, "error": type(exc).__name__},
            )
        else:
            self.last_warmup = "loaded"
            log.info("model warmed up", extra={"model": profile.processing_model})

    async def aclose(self) -> None:
        for task in list(self._warmups):
            task.cancel()
        await asyncio.gather(*self._warmups, return_exceptions=True)
        for adapter in self._adapters.values():
            await adapter.aclose()
