/**
 * Wrapper `fetch` duy nhất của app — luật thép L5 (plan.md §7.3).
 *
 * Ba điều file này cưỡng chế:
 *
 * 1. **Không `console.*` ở bất kỳ nhánh nào**, kể cả nhánh lỗi. Đây là chỗ mà
 *    một dòng `console.log(await res.json())` lúc debug sẽ sống sót tới
 *    production và in trọn profile khách ra console trình duyệt.
 * 2. **Không bao giờ ném JSON thô ra ngoài.** Mọi lỗi thành `ApiError` chỉ có
 *    `code` + `message` — đúng hình dạng backend trả về.
 * 3. **Không nuốt lỗi.** Mất mạng / server trả HTML / JSON hỏng đều thành một
 *    `ApiError` có câu tiếng Việt, không phải `undefined` trôi vào UI.
 *
 * Muốn xem JSON thì **tải tệp** qua `GET /api/profiles/{id}/output.json`
 * (`Content-Disposition: attachment`), không in ra console (§7.3.7).
 */

import type { ApiErrorBody } from './types'

/** Mã lỗi dùng khi chính tầng vận chuyển hỏng (chưa tới được backend). */
export const E_NETWORK = 'E-NET-000'
export const E_BAD_SHAPE = 'E-NET-002'

export class ApiError extends Error {
  readonly code: string
  readonly httpStatus: number

  constructor(code: string, message: string, httpStatus: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.httpStatus = httpStatus
  }

  /** Câu hiển thị cho người vận hành: câu tiếng Việt + mã ngắn để đối chiếu log. */
  get display(): string {
    return `${this.message} (${this.code})`
  }

  /**
   * 409 = "chưa cấu hình / hết phiên" → việc cần làm nằm ở trang Cài đặt.
   * Tách ra để UI điều hướng đúng chỗ thay vì chỉ hiện toast đỏ.
   */
  get needsSettings(): boolean {
    return this.httpStatus === 409 || this.code.startsWith('E-LLM-400-MODEL')
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
  /** Query string — ghép ở đây để không chỗ nào tự nối chuỗi URL. */
  query?: Record<string, string | number | boolean | undefined>
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  if (!query) return path
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined) params.set(key, String(value))
  }
  const qs = params.toString()
  return qs ? `${path}?${qs}` : path
}

/**
 * Bóc `{code, message}` khỏi response lỗi.
 *
 * Nếu thân không đúng hình dạng đó (vd nginx trả trang HTML 502), ta **không**
 * đưa thân đó ra UI — nó có thể dài hàng KB và chứa thông tin hạ tầng. Thay vào
 * đó là một câu tiếng Việt kèm mã HTTP.
 */
async function toApiError(response: Response): Promise<ApiError> {
  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    // Thân không phải JSON — bỏ qua, dùng câu mặc định theo status.
  }

  if (
    body !== null &&
    typeof body === 'object' &&
    typeof (body as ApiErrorBody).code === 'string' &&
    typeof (body as ApiErrorBody).message === 'string'
  ) {
    const typed = body as ApiErrorBody
    return new ApiError(typed.code, typed.message, response.status)
  }

  return new ApiError(
    `E-HTTP-${response.status}`,
    response.status >= 500
      ? 'Máy chủ gặp lỗi. Hãy thử lại sau ít phút.'
      : 'Yêu cầu không được chấp nhận.',
    response.status,
  )
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, signal, query } = options

  let response: Response
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      signal,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch (cause) {
    // `AbortError` là người dùng/React chủ động huỷ — không phải sự cố, phải
    // ném lại nguyên dạng để TanStack Query nhận ra và không hiện toast lỗi.
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause
    throw new ApiError(
      E_NETWORK,
      'Không kết nối được máy chủ. Kiểm tra API có đang chạy không.',
      0,
    )
  }

  if (!response.ok) throw await toApiError(response)

  // 204 / thân rỗng là hợp lệ với một số endpoint.
  if (response.status === 204) return undefined as T

  try {
    return (await response.json()) as T
  } catch {
    throw new ApiError(E_BAD_SHAPE, 'Máy chủ trả về dữ liệu không đọc được.', response.status)
  }
}

export const api = {
  get: <T>(path: string, query?: RequestOptions['query'], signal?: AbortSignal) =>
    request<T>(path, { method: 'GET', query, signal }),
  post: <T>(path: string, body?: unknown, query?: RequestOptions['query']) =>
    request<T>(path, { method: 'POST', body, query }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PUT', body }),
  del: <T>(path: string, query?: RequestOptions['query']) =>
    request<T>(path, { method: 'DELETE', query }),
}

/**
 * Câu hiển thị cho **bất cứ** thứ gì rơi vào `catch`.
 *
 * Không `String(error)`: với một `Error` lạ, chuỗi đó có thể chứa stack trace và
 * đi thẳng vào DOM. Chỉ `ApiError` được tin là đã sạch.
 */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.display
  if (error instanceof DOMException && error.name === 'AbortError') return 'Đã huỷ yêu cầu.'
  return 'Có lỗi không lường trước. Hãy thử lại.'
}
