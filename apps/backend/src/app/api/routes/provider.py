from fastapi import APIRouter

from app.api.deps import GatewayDep, ProvidersDep
from app.llm.gateway import LlmGateway
from app.llm.provider import Providers
from app.schemas.provider import ProviderIn, ProviderOut, ProviderProfileOut

router = APIRouter(prefix="/_provider", tags=["provider"])


def _view(providers: Providers, gateway: LlmGateway) -> ProviderOut:
    return ProviderOut(
        current=providers.current.name,
        profiles=[ProviderProfileOut(**p.model_dump()) for p in providers.profiles],
        warm_up=providers.last_warmup,
        breakers=gateway.breaker_states(),
    )


@router.get("")
async def get_provider(providers: ProvidersDep, gateway: GatewayDep) -> ProviderOut:
    """The provider profile in use, kept in memory only (docs/simulator.md)."""
    return _view(providers, gateway)


@router.put("")
async def put_provider(
    body: ProviderIn, providers: ProvidersDep, gateway: GatewayDep
) -> ProviderOut:
    """Switch provider profile. Requests in flight keep theirs (Processing NFR-5)."""
    providers.switch(body.provider)
    return _view(providers, gateway)
