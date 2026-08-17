from dataclasses import dataclass

from app.core.config import settings as env_settings


@dataclass
class RuntimeSettings:
    """Config del PBX editable en caliente desde la API, con los valores de
    entorno como default inicial hasta que se cargue la fila de BD."""

    app_name: str = env_settings.app_name
    fs_domain: str = env_settings.fs_domain
    fs_esl_host: str = env_settings.fs_esl_host
    fs_esl_port: int = env_settings.fs_esl_port
    fs_esl_password: str = env_settings.fs_esl_password
    fs_http_base: str = env_settings.fs_http_base


runtime_settings = RuntimeSettings()
