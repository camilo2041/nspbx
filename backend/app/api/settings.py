from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as env_settings
from app.core.database import get_session
from app.core.runtime_settings import runtime_settings
from app.models import SystemSettings
from app.schemas import SystemSettingsOut, SystemSettingsUpdate
from app.services import esl

router = APIRouter(prefix="/api/system", tags=["system"])


async def get_or_create_settings(session: AsyncSession) -> SystemSettings:
    row = await session.get(SystemSettings, 1)
    if not row:
        # Semilla inicial desde las variables de entorno del contenedor
        # (docker-compose), no desde los defaults estáticos del modelo.
        row = SystemSettings(
            id=1,
            app_name=env_settings.app_name,
            fs_domain=env_settings.fs_domain,
            fs_esl_host=env_settings.fs_esl_host,
            fs_esl_port=env_settings.fs_esl_port,
            fs_esl_password=env_settings.fs_esl_password,
            fs_http_base=env_settings.fs_http_base,
            sip_ws_url=env_settings.sip_ws_url,
            sip_server_ip=env_settings.sip_server_ip,
            sip_server_port=env_settings.sip_server_port,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


def apply_to_runtime(row: SystemSettings):
    runtime_settings.app_name = row.app_name
    runtime_settings.fs_domain = row.fs_domain
    runtime_settings.fs_esl_host = row.fs_esl_host
    runtime_settings.fs_esl_port = row.fs_esl_port
    runtime_settings.fs_esl_password = row.fs_esl_password
    runtime_settings.fs_http_base = row.fs_http_base


@router.get("/settings", response_model=SystemSettingsOut)
async def get_settings(session: AsyncSession = Depends(get_session)):
    return await get_or_create_settings(session)


@router.put("/settings", response_model=SystemSettingsOut)
async def update_settings(
    payload: SystemSettingsUpdate, session: AsyncSession = Depends(get_session)
):
    row = await get_or_create_settings(session)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    await session.commit()
    await session.refresh(row)
    apply_to_runtime(row)
    await esl.invalidate_client()
    return row
