from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.clock import a_hora_local


class TrunkBase(BaseModel):
    name: str
    gateway_host: str
    gateway_port: int = 5060
    username: Optional[str] = None
    password: Optional[str] = None
    from_domain: Optional[str] = None
    register_enabled: bool = True
    caller_id_number: Optional[str] = None
    transport: str = Field(default="udp", pattern="^(udp|tcp|tls)$")
    ping: Optional[int] = Field(default=None, ge=5, le=300)
    codec_prefs: Optional[str] = None
    enabled: bool = True


class TrunkCreate(TrunkBase):
    pass


class TrunkUpdate(BaseModel):
    name: Optional[str] = None
    gateway_host: Optional[str] = None
    gateway_port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    from_domain: Optional[str] = None
    register_enabled: Optional[bool] = None
    caller_id_number: Optional[str] = None
    transport: Optional[str] = Field(default=None, pattern="^(udp|tcp|tls)$")
    ping: Optional[int] = Field(default=None, ge=5, le=300)
    codec_prefs: Optional[str] = None
    enabled: Optional[bool] = None


class TrunkOut(TrunkBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class ExtensionBase(BaseModel):
    number: str
    password: str
    caller_id_name: Optional[str] = None
    voicemail: bool = True
    enabled: bool = True


class ExtensionCreate(ExtensionBase):
    pass


class ExtensionUpdate(BaseModel):
    number: Optional[str] = None
    password: Optional[str] = None
    caller_id_name: Optional[str] = None
    voicemail: Optional[bool] = None
    enabled: Optional[bool] = None


class ExtensionOut(ExtensionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class VoiceBotTtsRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    voice: str = Field(..., min_length=1, max_length=100)
    provider: str = Field(default="edge", pattern="^(edge|elevenlabs|deepgram)$")


class VoiceBotNodeTtsRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    voice: str = Field(..., min_length=1, max_length=100)
    kind: str = Field(default="audio", pattern="^(audio|whisper)$")
    provider: str = Field(default="edge", pattern="^(edge|elevenlabs|deepgram)$")


class VoiceBotFlowUpdate(BaseModel):
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)


class CallRequest(BaseModel):
    destination: str = Field(..., min_length=1, max_length=30)
    trunk_id: Optional[int] = None


class VoiceBotBase(BaseModel):
    name: str
    bot_type: str = "ivr"
    welcome_message: Optional[str] = None
    config: Optional[str] = None
    enabled: bool = True


class VoiceBotCreate(VoiceBotBase):
    pass


class VoiceBotUpdate(BaseModel):
    name: Optional[str] = None
    bot_type: Optional[str] = None
    welcome_message: Optional[str] = None
    config: Optional[str] = None
    enabled: Optional[bool] = None


class VoiceBotOut(VoiceBotBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    greeting_audio_path: Optional[str] = None
    flow_json: Optional[str] = None


class CampaignBase(BaseModel):
    name: str
    trunk_id: Optional[int] = None
    voicebot_id: Optional[int] = None
    max_concurrency: int = Field(default=5, ge=1, le=100)
    retries: int = Field(default=0, ge=0, le=10)
    message_template: Optional[str] = None


class CampaignCreate(CampaignBase):
    pass


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    trunk_id: Optional[int] = None
    voicebot_id: Optional[int] = None
    max_concurrency: Optional[int] = Field(default=None, ge=1, le=100)
    retries: Optional[int] = Field(default=None, ge=0, le=10)
    message_template: Optional[str] = None


class CampaignOut(CampaignBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class SystemSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    app_name: str
    fs_domain: str
    fs_esl_host: str
    fs_esl_port: int
    fs_esl_password: str
    fs_http_base: str
    sip_ws_url: str
    sip_server_ip: str
    sip_server_port: int
    elevenlabs_api_key: Optional[str] = None
    agent_webhook_secret: Optional[str] = None
    ai_llm_provider_name: str = "DeepSeek"
    ai_llm_base_url: str = "https://api.deepseek.com/v1"
    ai_llm_model: str = "deepseek-chat"
    ai_llm_api_key: Optional[str] = None
    deepgram_api_key: Optional[str] = None
    record_all_calls: bool = False
    ai_stt_provider: str = "elevenlabs"
    ai_voice_provider: str = "elevenlabs"
    ai_voice_id: str = "Xb7hH8MSUJpSbSDYk0k2"
    rate_tts_per_1k_chars: float = 0.0655
    rate_stt_per_minute: float = 0.0065
    rate_dg_tts_per_1k_chars: float = 0.030
    rate_dg_stt_per_minute: float = 0.00483
    rate_llm_in_per_1m: float = 0.04
    rate_llm_out_per_1m: float = 0.04
    backup_enabled: bool = True
    backup_retention_days: int = 14
    last_backup_at: Optional[datetime] = None
    last_backup_ok: Optional[bool] = None
    last_backup_error: Optional[str] = None
    recordings_retention_days: int = 90
    recordings_max_gb: float = 20.0
    backups_max_gb: float = 5.0
    max_call_duration_minutes: int = 60
    max_concurrent_calls: int = 20
    max_concurrent_ai_calls: int = 20


class SystemSettingsUpdate(BaseModel):
    app_name: Optional[str] = None
    fs_domain: Optional[str] = None
    fs_esl_host: Optional[str] = None
    fs_esl_port: Optional[int] = None
    fs_esl_password: Optional[str] = None
    fs_http_base: Optional[str] = None
    sip_ws_url: Optional[str] = None
    sip_server_ip: Optional[str] = None
    sip_server_port: Optional[int] = None
    elevenlabs_api_key: Optional[str] = None
    agent_webhook_secret: Optional[str] = None
    ai_llm_provider_name: Optional[str] = None
    ai_llm_base_url: Optional[str] = None
    ai_llm_model: Optional[str] = None
    ai_llm_api_key: Optional[str] = None

    deepgram_api_key: Optional[str] = None

    record_all_calls: Optional[bool] = None
    ai_stt_provider: Optional[str] = Field(default=None, pattern="^(elevenlabs|deepgram)$")
    ai_voice_provider: Optional[str] = Field(default=None, pattern="^(edge|elevenlabs|deepgram)$")
    ai_voice_id: Optional[str] = None

    # Tarifas para estimar el costo del consumo medido. Se ajustan al plan
    # real de cada proveedor: el valor por defecto del TTS sale del panel
    # de ElevenLabs del usuario ($0.15 por 2.290 caracteres).
    rate_tts_per_1k_chars: Optional[float] = Field(default=None, ge=0)
    rate_stt_per_minute: Optional[float] = Field(default=None, ge=0)
    rate_dg_tts_per_1k_chars: Optional[float] = Field(default=None, ge=0)
    rate_dg_stt_per_minute: Optional[float] = Field(default=None, ge=0)
    rate_llm_in_per_1m: Optional[float] = Field(default=None, ge=0)
    rate_llm_out_per_1m: Optional[float] = Field(default=None, ge=0)

    backup_enabled: Optional[bool] = None
    backup_retention_days: Optional[int] = Field(default=None, ge=1, le=365)
    recordings_retention_days: Optional[int] = Field(default=None, ge=1, le=3650)
    recordings_max_gb: Optional[float] = Field(default=None, ge=0.5)
    backups_max_gb: Optional[float] = Field(default=None, ge=0.5)
    # 0 = sin tope. El resto de los campos de esta clase no admite 0 (no
    # tendría sentido "cero días de retención"), pero acá sí es un valor
    # legítimo para quien de verdad necesita llamadas sin límite de tiempo.
    max_call_duration_minutes: Optional[int] = Field(default=None, ge=0, le=1440)
    max_concurrent_calls: Optional[int] = Field(default=None, ge=1, le=500)
    max_concurrent_ai_calls: Optional[int] = Field(default=None, ge=1, le=500)


class CallLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: Optional[str] = None
    caller_number: Optional[str] = None
    caller_name: Optional[str] = None
    callee_number: Optional[str] = None
    direction: str
    status: str
    duration: int
    billsec: int
    hangup_cause: Optional[str] = None
    recording_path: Optional[str] = None
    has_recording: bool = False
    started_at: Optional[datetime] = None
    answered_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None


class CampaignNumberRow(BaseModel):
    phone: str = Field(..., min_length=1, max_length=30)
    # Variables para esta llamada puntual (ej. {"cliente": "...", "fecha":
    # "2026-08-21 09:00"}) — rellenan Campaign.message_template. Si trae
    # "cliente" y "fecha", además se usa para cargar/actualizar la cita en
    # la Agenda (ver add_numbers en app/api/campaigns.py).
    vars: dict[str, str] = Field(default_factory=dict)


class CampaignNumberIn(BaseModel):
    numbers: list[CampaignNumberRow] = Field(..., min_length=1, max_length=10000)


class CampaignNumberUpdate(BaseModel):
    phone: str = Field(..., min_length=1, max_length=30)
    vars: Optional[dict[str, str]] = None


class InboundRouteBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    did_pattern: str = Field(..., min_length=1, max_length=100)
    destination_type: str = Field(..., pattern="^(extension|queue|voicebot|hangup)$")
    destination_value: Optional[str] = None
    priority: int = Field(default=10, ge=0, le=1000)
    enabled: bool = True


class InboundRouteCreate(InboundRouteBase):
    pass


class InboundRouteUpdate(BaseModel):
    name: Optional[str] = None
    did_pattern: Optional[str] = None
    destination_type: Optional[str] = Field(default=None, pattern="^(extension|queue|voicebot|hangup)$")
    destination_value: Optional[str] = None
    priority: Optional[int] = Field(default=None, ge=0, le=1000)
    enabled: Optional[bool] = None


class InboundRouteOut(InboundRouteBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class AppointmentBase(BaseModel):
    patient_name: str = Field(..., min_length=1, max_length=150)
    phone: str = Field(..., min_length=1, max_length=30)
    appointment_date: datetime
    duration_minutes: int = Field(default=30, ge=5, le=480)
    status: str = Field(default="confirmed", pattern="^(confirmed|cancelled|completed)$")
    notes: Optional[str] = None

    # El navegador manda la fecha en UTC con sufijo Z. Sin normalizarla acá
    # entraba con zona a la capa de agenda y reventaba al compararla contra
    # las fechas naive de la base (500 al crear una cita en un día que ya
    # tuviera otra), además de correr la hora 5 puestos.
    @field_validator("appointment_date")
    @classmethod
    def _normalizar_fecha(cls, v: datetime) -> datetime:
        return a_hora_local(v)


class AppointmentCreate(AppointmentBase):
    pass


class AppointmentUpdate(BaseModel):
    patient_name: Optional[str] = None
    phone: Optional[str] = None
    appointment_date: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(default=None, ge=5, le=480)
    status: Optional[str] = Field(default=None, pattern="^(confirmed|cancelled|completed)$")
    notes: Optional[str] = None

    @field_validator("appointment_date")
    @classmethod
    def _normalizar_fecha(cls, v: datetime | None) -> datetime | None:
        return a_hora_local(v) if v else v


class AppointmentOut(AppointmentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class AgentBookRequest(BaseModel):
    patient_name: str = Field(..., min_length=1, max_length=150)
    phone: str = Field(..., min_length=1, max_length=30)
    date: str = Field(..., description="YYYY-MM-DD")
    time: str = Field(..., description="HH:MM, 24h")
    duration_minutes: int = Field(default=30, ge=5, le=480)
    notes: Optional[str] = None


class AgentCancelRequest(BaseModel):
    phone: str = Field(..., min_length=1, max_length=30)
    date: Optional[str] = Field(default=None, description="YYYY-MM-DD; si se omite, cancela la próxima cita de ese teléfono")


class AgentRescheduleRequest(BaseModel):
    phone: str = Field(..., min_length=1, max_length=30)
    old_date: Optional[str] = Field(default=None, description="YYYY-MM-DD de la cita a mover; si se omite, se toma la próxima")
    new_date: str = Field(..., description="YYYY-MM-DD")
    new_time: str = Field(..., description="HH:MM, 24h")


class QueueBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    extension: str = Field(..., min_length=1, max_length=30)
    strategy: str = Field(
        default="ring-all",
        pattern="^(ring-all|round-robin|top-down|longest-idle-agent|agent-with-least-talk-time|agent-with-fewest-calls|sequentially-by-agent-order|random)$",
    )
    moh_sound: str = "$${hold_music}"
    agents: list[str] = Field(default_factory=list)
    max_wait_time: int = Field(default=0, ge=0)
    max_wait_time_with_no_agent: int = Field(default=0, ge=0)
    agent_ring_timeout: int = Field(default=20, ge=3, le=120)
    max_no_answer: int = Field(default=3, ge=0, le=20)
    wrap_up_time: int = Field(default=10, ge=0, le=600)
    record: bool = False
    failover_extension: Optional[str] = None
    announce_position: bool = False
    enabled: bool = True


class QueueCreate(QueueBase):
    pass


class QueueUpdate(BaseModel):
    name: Optional[str] = None
    extension: Optional[str] = None
    strategy: Optional[str] = Field(default=None, pattern="^(ring-all|round-robin|top-down|longest-idle-agent|agent-with-least-talk-time|agent-with-fewest-calls|sequentially-by-agent-order|random)$")
    moh_sound: Optional[str] = None
    agents: Optional[list[str]] = None
    max_wait_time: Optional[int] = Field(default=None, ge=0)
    max_wait_time_with_no_agent: Optional[int] = Field(default=None, ge=0)
    agent_ring_timeout: Optional[int] = Field(default=None, ge=3, le=120)
    max_no_answer: Optional[int] = Field(default=None, ge=0, le=20)
    wrap_up_time: Optional[int] = Field(default=None, ge=0, le=600)
    record: Optional[bool] = None
    failover_extension: Optional[str] = None
    announce_position: Optional[bool] = None
    enabled: Optional[bool] = None


class QueueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    extension: str
    strategy: str
    moh_sound: str
    agents: list[str]
    max_wait_time: int
    max_wait_time_with_no_agent: int
    agent_ring_timeout: int
    max_no_answer: int
    wrap_up_time: int
    record: bool
    failover_extension: Optional[str] = None
    announce_position: bool
    enabled: bool
    created_at: datetime


class CampaignStats(BaseModel):
    total: int = 0
    pending: int = 0
    dialing: int = 0
    answered: int = 0
    busy: int = 0
    noanswer: int = 0
    failed: int = 0
    done: int = 0
    active_calls: int = 0


# ---------- Usuarios y sesión ----------

_ROLES_PATRON = "^(admin|supervisor|coordinador|asesor)$"


class UserBase(BaseModel):
    username: str = Field(min_length=3, max_length=60)
    full_name: str = Field(min_length=2, max_length=150)
    email: Optional[str] = Field(default=None, max_length=150)
    role: str = Field(default="asesor", pattern=_ROLES_PATRON)
    extension_id: Optional[int] = None
    enabled: bool = True

    @field_validator("username")
    @classmethod
    def _usuario_limpio(cls, v: str) -> str:
        v = v.strip().lower()
        if not v.replace(".", "").replace("_", "").replace("-", "").isalnum():
            raise ValueError("El usuario solo admite letras, números, punto, guion y guion bajo")
        return v

    @field_validator("email")
    @classmethod
    def _email_plausible(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("El correo no parece válido")
        return v


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserUpdate(BaseModel):
    """Todo opcional: se actualiza solo lo que venga."""

    full_name: Optional[str] = Field(default=None, min_length=2, max_length=150)
    email: Optional[str] = Field(default=None, max_length=150)
    role: Optional[str] = Field(default=None, pattern=_ROLES_PATRON)
    extension_id: Optional[int] = None
    enabled: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    full_name: str
    email: Optional[str] = None
    role: str
    extension_id: Optional[int] = None
    # Se resuelve en el endpoint para no obligar a la interfaz a cruzar
    # la lista de extensiones solo para mostrar un número.
    extension_number: Optional[str] = None
    enabled: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime


class LoginRequest(BaseModel):
    username: str
    password: str


class SesionOut(BaseModel):
    """Lo que necesita la interfaz para arrancar: quién es y qué puede."""

    token: str
    expira_en: int
    usuario: UserOut
    permisos: list[str]


class CambiarPasswordRequest(BaseModel):
    password_actual: str
    password_nueva: str = Field(min_length=8, max_length=128)


# ---------- Rutas Salientes, Horarios y Lista Negra ----------

class OutboundRouteBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    match_pattern: str = Field(..., min_length=1, max_length=100)
    strip_digits: int = Field(default=0, ge=0, le=20)
    prepend_digits: Optional[str] = Field(default=None, max_length=30)
    trunk_id: Optional[int] = None
    priority: int = Field(default=10, ge=1, le=1000)
    enabled: bool = True


class OutboundRouteCreate(OutboundRouteBase):
    pass


class OutboundRouteUpdate(BaseModel):
    name: Optional[str] = None
    match_pattern: Optional[str] = None
    strip_digits: Optional[int] = Field(default=None, ge=0, le=20)
    prepend_digits: Optional[str] = None
    trunk_id: Optional[int] = None
    priority: Optional[int] = Field(default=None, ge=1, le=1000)
    enabled: Optional[bool] = None


class OutboundRouteOut(OutboundRouteBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class TimeGroupBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    schedule_json: str = Field(default="[]")


class TimeGroupCreate(TimeGroupBase):
    pass


class TimeGroupUpdate(BaseModel):
    name: Optional[str] = None
    schedule_json: Optional[str] = None


class TimeGroupOut(TimeGroupBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class TimeConditionBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    time_group_id: int
    match_destination_type: str = Field(..., pattern="^(extension|queue|voicebot|hangup)$")
    match_destination_value: Optional[str] = None
    nomatch_destination_type: str = Field(..., pattern="^(extension|queue|voicebot|hangup)$")
    nomatch_destination_value: Optional[str] = None
    enabled: bool = True


class TimeConditionCreate(TimeConditionBase):
    pass


class TimeConditionUpdate(BaseModel):
    name: Optional[str] = None
    time_group_id: Optional[int] = None
    match_destination_type: Optional[str] = Field(default=None, pattern="^(extension|queue|voicebot|hangup)$")
    match_destination_value: Optional[str] = None
    nomatch_destination_type: Optional[str] = Field(default=None, pattern="^(extension|queue|voicebot|hangup)$")
    nomatch_destination_value: Optional[str] = None
    enabled: Optional[bool] = None


class TimeConditionOut(TimeConditionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class BlacklistBase(BaseModel):
    phone: str = Field(..., min_length=1, max_length=30)
    note: Optional[str] = Field(default=None, max_length=255)


class BlacklistCreate(BlacklistBase):
    pass


class BlacklistOut(BlacklistBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime

