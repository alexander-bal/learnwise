from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tasks import TaskTracker
from app.llm.gateway import LlmGateway
from app.llm.provider import Providers
from app.services.processing import ProcessingService


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def get_processing(request: Request) -> ProcessingService:
    return request.app.state.processing


def get_providers(request: Request) -> Providers:
    return request.app.state.providers


def get_gateway(request: Request) -> LlmGateway:
    return request.app.state.gateway


def get_tasks(request: Request) -> TaskTracker:
    return request.app.state.tasks


SessionDep = Annotated[AsyncSession, Depends(get_session)]
ProcessingDep = Annotated[ProcessingService, Depends(get_processing)]
ProvidersDep = Annotated[Providers, Depends(get_providers)]
GatewayDep = Annotated[LlmGateway, Depends(get_gateway)]
TasksDep = Annotated[TaskTracker, Depends(get_tasks)]
