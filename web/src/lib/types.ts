/**
 * Kiểu dữ liệu API — bản sao hợp đồng của `app/schemas/api.py`.
 *
 * Viết tay thay vì sinh từ OpenAPI là có chủ đích: `/openapi.json` **tắt mặc
 * định** (plan.md §7.2), nên một bước sinh code phụ thuộc vào việc bật nó lên
 * sẽ vỡ đúng lúc build production. Đổi lại, mọi field ở đây phải khớp tay với
 * backend — và `no-explicit-any` trong ESLint bảo đảm không ai lách bằng `any`.
 */

/** Thân response lỗi — **luôn** chỉ có `code` + `message` (plan.md §7.3.6). */
export interface ApiErrorBody {
  code: string
  message: string
}

export type ProviderName = 'antigravity' | 'google_api_key'

export interface CredentialInfo {
  is_set: boolean
  hint: string
  created_at: string | null
}

export interface ModelInfo {
  id: string
  display_name: string
  /** `null` = **chưa biết** (cổng B không trả cờ vision). Không được quy về `false`. */
  supports_vision: boolean | null
  input_token_limit: number | null
  output_token_limit: number | null
}

export interface ModelList {
  provider: string
  models: ModelInfo[]
  selected: string | null
  note: string
}

export interface LlmStatus {
  provider: string | null
  model: string | null
  temperature: number
  max_output_tokens: number
  /** `reachable` ≠ `connected`: cổng sống nhưng chưa đăng nhập thì cần bấm "Đăng nhập". */
  reachable: boolean
  connected: boolean
  account: string | null
  detail: string
  latency_ms: number | null
  must_choose_model: boolean
  api_key: CredentialInfo
}

export interface OAuthStart {
  url: string
  state: string
}

export interface OAuthStatus {
  status: 'wait' | 'ok' | 'error'
  message: string
  connected: boolean
  account: string | null
}

export interface GatewayTest {
  ok: boolean
  provider: string
  model: string
  latency_ms: number
  note: string
}

export interface ActionResult {
  ok: boolean
  message: string
}

// ---------------------------------------------------------------------------
// Profiles
// ---------------------------------------------------------------------------
export type ProfileStatus = 'SUCCESS' | 'PARTIAL_OR_PRIVATE' | 'FAILED_VALIDATION' | 'ERROR'

/** Sáu bước của timeline (app/services/progress.py). */
export type StepName = 'collect' | 'images' | 'profile' | 'messages' | 'hook' | 'moderation'
export type StepState = 'pending' | 'running' | 'done' | 'skipped' | 'failed'

export interface Step {
  step: StepName | string
  label: string
  state: StepState | string
  note: string
  started_at: string | null
  finished_at: string | null
}

export interface Job {
  job_id: string
  job_name: string
  /** `null` = **đang chạy**. `false` suốt 70 giây sẽ là một lời nói sai. */
  ok: boolean | null
  started_at: string | null
  finished_at: string | null
  steps: Step[]
  profile_id: string | null
  status: string | null
  error: string | null
}

export interface AnalyzeAccepted {
  job_id: string | null
  profile_id: string | null
  reused: boolean
  message: string
}

export interface EvidenceField {
  key: string
  value: string | null
  source: string
  evidence: string
  confidence: number | null
}

export interface EvidenceImage {
  role: string
  local_path: string | null
  sha256: string
}

export interface EvidencePanel {
  layers_used: string[]
  blocked_reason: string | null
  screenshot_path: string | null
  fields: EvidenceField[]
  images: EvidenceImage[]
}

export interface ProfileSummary {
  id: string
  facebook_url: string
  customer_name: string | null
  status: ProfileStatus | string
  created_at: string
  message_count: number
  sales_check: string | null
}

export interface ProfileList {
  items: ProfileSummary[]
  total: number
  limit: number
  offset: number
}

export interface ProfileDetail {
  id: string
  facebook_url: string
  status: ProfileStatus | string
  created_at: string
  customer_name: string | null
  visual_context: string | null
  /** Gồm cả `basis` — đường truy vết căn cứ suy luận, chỉ hiện trên UI. */
  demographics: Record<string, unknown>
  error_note: string | null
  core_empathy_angle: string | null
  messages: string[]
  sales_mention_check: string | null
  evening_hook_message: string | null
  trigger_time: string
  /**
   * Bản ghi có strict JSON lưu kèm hay không (task.md I-46).
   * `messages = []` + `has_stored_output = false` nghĩa là **dữ liệu cũ**, không
   * phải "nội dung bị kiểm duyệt loại". Hai thứ phải nói khác nhau.
   */
  has_stored_output: boolean
  provider: string | null
  model: string | null
  latency_ms: number | null
  evidence: EvidencePanel
  job: Job | null
}

export interface AnalyzeRequest {
  facebook_url?: string | null
  profile_text?: string | null
  use_playwright?: boolean
  refresh?: boolean
  messages?: number | null
}

// ---------------------------------------------------------------------------
// Outbox + thống kê
// ---------------------------------------------------------------------------
export type OutboxStatus = 'draft' | 'approved' | 'sent_manually' | 'discarded'

export interface OutboxItem {
  id: string
  profile_id: string
  customer_name: string | null
  facebook_url: string | null
  message: string | null
  status: OutboxStatus | string
  scheduled_for: string
  acted_at: string | null
  created_at: string
}

export interface OutboxList {
  items: OutboxItem[]
  total: number
  limit: number
  offset: number
}

export interface DashboardStats {
  profiles_total: number
  profiles_success: number
  profiles_partial: number
  profiles_failed: number
  /** `null` khi chưa có profile nào — hiện "0%" cho mẫu rỗng là nói sai. */
  readable_rate: number | null
  hooks_waiting: number
  messages_total: number
}

export interface SchedulerStatus {
  enabled: boolean
  running: boolean
  next_run_at: string | null
  cron: string
  detail: string
}

export interface Health {
  status: string
  db: string
  provider: string | null
  model: string | null
  dry_run: boolean
  scheduler: SchedulerStatus
}

// ---------------------------------------------------------------------------
// Cookie Facebook của chính người vận hành (task.md X.2)
// ---------------------------------------------------------------------------
export interface CookieStatus {
  is_set: boolean
  /** `100012345678901` → `••••8901`. Không bao giờ là giá trị cookie thật. */
  masked_account: string
  names: string[]
  created_at: string | null
  risk_warning: string
  /** `null` = chưa kiểm. */
  alive: boolean | null
}

// ---------------------------------------------------------------------------
// Hội thoại nhiều lượt (task.md X.3 / X.4 / X.6)
// ---------------------------------------------------------------------------
export type MessageRole = 'operator' | 'customer'

export interface ConversationMessage {
  id: string
  seq: number
  role: MessageRole | string
  text: string
  created_at: string
  /**
   * Tin được tạo ở **chế độ demo** — không có tin thật nào đi hay đến.
   *
   * Backend suy ra từ `external_id` bắt đầu bằng `demo:`. Giao diện **phải**
   * hiện rõ, kể cả sau khi đã tắt chế độ demo: nếu bản ghi demo trông y hệt bản
   * ghi thật thì sau buổi trình bày không ai phân biệt được tin nào đã thật sự
   * gửi cho khách.
   */
  is_demo: boolean
}

export interface Suggestion {
  id: string
  round: number
  seq: number
  text: string
  chosen: boolean
}

export interface Conversation {
  id: string
  /**
   * `null` khi hội thoại sinh từ webhook Messenger — người đó nhắn Page trước
   * khi được phân tích, nên chưa có profile nào để trỏ tới.
   */
  profile_id: string | null
  customer_name: string | null
  facebook_url: string | null
  status: string
  created_at: string
  closed_at: string | null
  messages: ConversationMessage[]
  suggestions: Suggestion[]
  suggestion_round: number
  /**
   * Page-Scoped ID. Chỉ có khi người này đã **chủ động nhắn Page** — nên nó vừa
   * là địa chỉ gửi, vừa là bằng chứng họ đồng ý nhận tin.
   */
  psid: string | null
  /**
   * `true` = gửi tự động được (có `psid` + đã kết nối Page).
   *
   * Dùng cờ này để chọn giữa nút "Gửi" **thật** và đường thủ công, thay vì tự
   * suy từ `psid` ở phía FE — backend là nơi duy nhất biết đủ điều kiện.
   */
  can_send: boolean
  /**
   * Link **trang cá nhân** — đích duy nhất dùng được cho đường thủ công.
   *
   * Không có `messenger_url`: Facebook không còn URL điều hướng được tới chat
   * cá nhân. Bấm "Nhắn tin" trên trang profile mở khung chat **ngay trong
   * trang**, URL không đổi (task.md I-60, đo thật trên phiên đã đăng nhập).
   */
  profile_url: string | null
  /** Câu giải thích khi lượt gợi ý vừa rồi không có câu nào sạch. */
  suggestion_note: string
}

export interface ConversationSummary {
  id: string
  profile_id: string | null
  customer_name: string | null
  status: string
  created_at: string
  message_count: number
  last_message_at: string | null
}

export interface ConversationList {
  items: ConversationSummary[]
  total: number
}

// ---------------------------------------------------------------------------
// Kết nối Facebook Page — gửi/nhận tự động (task.md X.6)
// ---------------------------------------------------------------------------
export interface PageStatus {
  is_set: boolean
  /** Vài ký tự đầu/cuối của token. **Không bao giờ** là giá trị thật (luật L4). */
  hint: string
  /** Tên Page lấy thật từ Graph API. `null` = Facebook không nhận token. */
  page_name: string | null
  /** Đã đủ `MESSENGER_APP_SECRET` + `MESSENGER_VERIFY_TOKEN` để nhận webhook. */
  webhook_ready: boolean
  /** Đường người dùng phải dán vào Meta for Developers. */
  webhook_url: string
  /** Lý do **cụ thể** vì sao chưa dùng được; rỗng nghĩa là đã sẵn sàng. */
  blocker: string
}
