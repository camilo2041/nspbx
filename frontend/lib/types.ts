export interface Trunk {
  id: number;
  name: string;
  gateway_host: string;
  gateway_port: number;
  username: string | null;
  password: string | null;
  from_domain: string | null;
  register_enabled: boolean;
  caller_id_number: string | null;
  transport: "udp" | "tcp" | "tls";
  ping: number | null;
  codec_prefs: string | null;
  enabled: boolean;
  created_at: string;
}

export interface TrunkStatus {
  state: string | null;
  status: string | null;
  ping_ms: string | null;
}

export interface Extension {
  id: number;
  number: string;
  password: string;
  caller_id_name: string | null;
  voicemail: boolean;
  enabled: boolean;
  created_at: string;
}

export interface TtsVoice {
  id: string;
  label: string;
}

export interface VoiceBot {
  id: number;
  name: string;
  bot_type: "ivr" | "ai";
  welcome_message: string | null;
  config: string | null;
  greeting_audio_path: string | null;
  flow_json: string | null;
  enabled: boolean;
  created_at: string;
}

export type FlowNodeType = "menu" | "transfer" | "hangup" | "ai_agent" | "pause";

export interface AiNodeExit {
  key: string;
  label: string;
}

export interface AiTemplate {
  key: string;
  label: string;
  prompt: string;
  tools: string[];
  max_turns: number;
  greeting: string;
  requiere_cita: boolean;
}

export interface FlowNodeData {
  [key: string]: unknown;
  label?: string;
  start?: boolean;
  audio_path?: string | null;
  tts_text?: string | null;
  extension?: string;
  // Nodo "transfer": a una extensión (por defecto, ver `extension` arriba)
  // o a una cola de mod_callcenter. `queue_name` es solo para mostrar en
  // el canvas sin tener que ir a buscarla — la fuente de verdad para el
  // dialplan es `queue_id`.
  target_type?: "extension" | "queue";
  queue_id?: number;
  queue_name?: string;
  whisper_audio_path?: string | null;
  // Legado: selección fija de gestión (ver ai_intents.py). El backend la
  // migra sola a un nodo "ai_agent" al leer el flujo — ya no se escribe
  // desde acá, solo puede seguir apareciendo en flujos viejos sin reabrir.
  ai_intent?: string;
  whisper_text?: string | null;
  // Nodo "ai_agent"
  prompt?: string;
  tools?: string[];
  greeting?: string;
  max_turns?: number;
  exits?: AiNodeExit[];
  campaign_entry?: boolean;
  requiere_cita?: boolean;
  // Nodo "pause": segundos de espera antes de seguir.
  seconds?: number;
}

export interface FlowNode {
  id: string;
  type: FlowNodeType;
  position: { x: number; y: number };
  data: FlowNodeData;
}

export interface FlowEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle: string;
}

export interface VoiceBotFlow {
  nodes: FlowNode[];
  edges: FlowEdge[];
}

export interface Campaign {
  id: number;
  name: string;
  trunk_id: number | null;
  voicebot_id: number | null;
  max_concurrency: number;
  retries: number;
  message_template: string | null;
  status: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface CampaignNumber {
  id: number;
  campaign_id: number;
  phone: string;
  status: string;
  attempts: number;
  last_error: string | null;
  vars: Record<string, string>;
  created_at: string;
}

export interface CampaignNumbersUploadResult {
  added: number;
  updated: number;
  total: number;
  agenda_creadas: number;
  agenda_omitidas: { phone: string; motivo: string }[];
}

export interface CampaignStats {
  total: number;
  pending: number;
  dialing: number;
  answered: number;
  busy: number;
  noanswer: number;
  failed: number;
  done: number;
  active_calls: number;
}

export interface CampaignWithStats extends Campaign {
  stats: CampaignStats;
  trunk_name?: string | null;
  voicebot_name?: string | null;
}

export interface InboundRoute {
  id: number;
  name: string;
  did_pattern: string;
  destination_type: "extension" | "queue" | "voicebot" | "time_condition" | "hangup";
  destination_value: string | null;
  priority: number;
  enabled: boolean;
  created_at: string;
}

export interface Queue {
  id: number;
  name: string;
  extension: string;
  strategy: string;
  moh_sound: string;
  agents: string[];
  max_wait_time: number;
  max_wait_time_with_no_agent: number;
  agent_ring_timeout: number;
  max_no_answer: number;
  wrap_up_time: number;
  record: boolean;
  failover_extension: string | null;
  announce_audio_path: string | null;
  announce_tts_text: string | null;
  announce_position: boolean;
  enabled: boolean;
  created_at: string;
}

export interface SystemSettings {
  app_name: string;
  fs_domain: string;
  fs_esl_host: string;
  fs_esl_port: number;
  fs_esl_password: string;
  fs_http_base: string;
  sip_ws_url: string;
  sip_server_ip: string;
  sip_server_port: number;
  elevenlabs_api_key: string | null;
  agent_webhook_secret: string | null;
  ai_llm_provider_name: string;
  ai_llm_base_url: string;
  ai_llm_model: string;
  ai_llm_api_key: string | null;
  deepgram_api_key: string | null;
  record_all_calls: boolean;
  ai_stt_provider: "elevenlabs" | "deepgram";
  ai_voice_provider: "edge" | "elevenlabs" | "deepgram";
  ai_voice_id: string;
  rate_tts_per_1k_chars: number;
  rate_stt_per_minute: number;
  rate_dg_tts_per_1k_chars: number;
  rate_dg_stt_per_minute: number;
  rate_llm_in_per_1m: number;
  rate_llm_out_per_1m: number;
  backup_enabled: boolean;
  backup_retention_days: number;
  last_backup_at: string | null;
  last_backup_ok: boolean | null;
  last_backup_error: string | null;
  recordings_retention_days: number;
  recordings_max_gb: number;
  backups_max_gb: number;
  max_call_duration_minutes: number;
  max_concurrent_calls: number;
  max_concurrent_ai_calls: number;
}

export interface MaintenanceStatus {
  backup_enabled: boolean;
  backup_retention_days: number;
  last_backup_at: string | null;
  last_backup_ok: boolean | null;
  last_backup_error: string | null;
  backups_count: number;
  backups_size_mb: number;
  recordings_retention_days: number;
  recordings_max_gb: number;
  recordings_count: number;
  recordings_size_gb: number;
}

export interface DetectedIp {
  lan_ip: string | null;
  public_ip: string | null;
}

export interface RecursosDisco {
  nombre: string;
  punto: string;
  total_gb: number;
  usado_gb: number;
  libre_gb: number;
  porcentaje: number;
}

export interface Recursos {
  cpu: { porcentaje: number; nucleos: number; por_nucleo: number[] };
  memoria: { total_gb: number; usado_gb: number; disponible_gb: number; porcentaje: number };
  swap: { total_gb: number; usado_gb: number; porcentaje: number };
  discos: RecursosDisco[];
}

export interface TrunkDiagnostic {
  id: number;
  name: string;
  gateway_host: string;
  register_enabled: boolean;
  state: string | null;
  status: string | null;
  contact_ip: string | null;
  contact_no_alcanzable: boolean;
}

export interface Diagnostics {
  esl_ok: boolean;
  sip_ws_ok: boolean;
  public_ip: string | null;
  trunks: TrunkDiagnostic[];
}

export interface Appointment {
  id: number;
  patient_name: string;
  phone: string;
  appointment_date: string;
  duration_minutes: number;
  status: "confirmed" | "cancelled" | "completed";
  notes: string | null;
  created_at: string;
}

export interface GestionRow {
  id: number;
  phone: string | null;
  action: "confirmada" | "cancelada" | "reagendada" | "agendada";
  patient_name: string | null;
  appointment_date: string | null;
  appointment_id: number | null;
  called_at: string;
}

export interface CallLog {
  id: number;
  uuid: string | null;
  caller_number: string | null;
  caller_name: string | null;
  callee_number: string | null;
  direction: "inbound" | "outbound";
  status: string;
  duration: number;
  billsec: number;
  hangup_cause: string | null;
  recording_path: string | null;
  has_recording: boolean;
  started_at: string | null;
  answered_at: string | null;
  ended_at: string | null;
}

export interface CallStats {
  total: number;
  answered: number;
  no_answer: number;
  busy: number;
  failed: number;
  talk_minutes: number;
}

// ---------- Usuarios y sesión ----------
// Los nombres de permiso son los mismos que en
// backend/app/core/permissions.py: si cambian allá, cambian acá.
export const PERMISOS = {
  usuarios: "usuarios:gestionar",
  ajustes: "ajustes:gestionar",
  telefonia: "telefonia:gestionar",
  colas: "colas:gestionar",
  campanas: "campanas:gestionar",
  voizbotsGestionar: "voizbots:gestionar",
  voizbotsVer: "voizbots:ver",
  llamadasTodas: "llamadas:ver_todas",
  llamadasPropias: "llamadas:ver_propias",
  citas: "citas:gestionar",
  consumoIa: "consumo_ia:ver",
  softphone: "softphone:usar",
} as const;

export type Rol = "admin" | "supervisor" | "coordinador" | "asesor";

export interface Usuario {
  id: number;
  username: string;
  full_name: string;
  email: string | null;
  role: Rol;
  extension_id: number | null;
  extension_number: string | null;
  enabled: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface Sesion {
  token: string;
  expira_en: number;
  usuario: Usuario;
  permisos: string[];
}

export interface RolInfo {
  value: Rol;
  label: string;
  description: string;
  requiere_extension: boolean;
  permisos: string[];
}

export interface MiEntorno {
  extension: {
    id: number;
    number: string;
    password: string;
    caller_id_name: string | null;
    enabled: boolean;
    dnd: boolean;
  } | null;
  fs_domain: string | null;
  sip_ws_url: string | null;
  sip_server_ip: string | null;
  sip_server_port: number | null;
  // STUN siempre; TURN solo si está configurado en el servidor. Las
  // credenciales llevan firma con vencimiento, ver app/services/turn.py.
  ice_servers: { urls: string[]; username?: string; credential?: string }[];
}

export interface OutboundRoute {
  id: number;
  name: string;
  match_pattern: string;
  strip_digits: number;
  prepend_digits: string | null;
  trunk_id: number | null;
  priority: number;
  enabled: boolean;
  created_at: string;
}

export interface TimeGroup {
  id: number;
  name: string;
  schedule_json: string;
  created_at: string;
}

export interface TimeCondition {
  id: number;
  name: string;
  time_group_id: number;
  match_destination_type: "extension" | "queue" | "voicebot" | "hangup";
  match_destination_value: string | null;
  nomatch_destination_type: "extension" | "queue" | "voicebot" | "hangup";
  nomatch_destination_value: string | null;
  enabled: boolean;
  created_at: string;
}

export interface BlacklistNumber {
  id: number;
  phone: string;
  note: string | null;
  created_at: string;
}

export interface PriorityNumber {
  id: number;
  number: string;
  note: string | null;
  created_at: string;
}

export interface RingGroup {
  id: number;
  name: string;
  number: string;
  members: string[];
  enabled: boolean;
  created_at: string;
}

export interface ActiveChannel {
  uuid: string;
  direction: string;
  created: string;
  name: string;
  state: string;
  cid_name: string;
  cid_num: string;
  dest: string;
  application: string;
  application_data: string;
}

