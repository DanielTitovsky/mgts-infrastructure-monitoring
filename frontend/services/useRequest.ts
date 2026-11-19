import config from '~/config'
import { useNotifications } from '~/composables/useNotifications'
import { mockRequest } from '~/services/mockApi'

type RequestBody = Record<string, unknown> | string | FormData

interface Options{
  method?: string,
  headers?: Record<string, string>,
  body?: RequestBody,
  removePreferHeader?: boolean,
  // Уведомления: silent отключает тосты, successMessage задаёт текст успеха
  // (false — не показывать), errorTitle переопределяет заголовок ошибки.
  silent?: boolean,
  successMessage?: string | false,
  errorTitle?: string
}

const MUTATION_METHODS = ['POST', 'PUT', 'PATCH', 'DELETE']

const DEFAULT_SUCCESS_MESSAGES: Record<string, string> = {
  POST: 'Действие выполнено',
  PUT: 'Изменения сохранены',
  PATCH: 'Изменения сохранены',
  DELETE: 'Удалено',
}

export function useRequest(url: string, options: Options = {}) {
  const notifications = useNotifications()
  const method = (options.method || 'GET').toUpperCase()

  function notifyResult(result: { success: boolean, error?: any }) {
    if (options.silent) return

    if (result.error) {
      const description = result.error.description
        || result.error.message
        || 'Не удалось выполнить действие. Попробуйте ещё раз.'

      notifications.error(description, options.errorTitle || result.error.title || 'Ошибка')
      return
    }

    if (options.successMessage === false) return

    if (typeof options.successMessage === 'string' && options.successMessage) {
      notifications.success(options.successMessage)
      return
    }

    if (MUTATION_METHODS.includes(method)) {
      notifications.success(DEFAULT_SUCCESS_MESSAGES[method] || 'Действие выполнено')
    }
  }

  if (config.useMocks) {
    return mockRequest(url, options).then((result) => {
      notifyResult(result)
      return result
    })
  }

  // На сервере относительный URL некуда резолвить: Nitro не проксирует
  // внутренние вызовы $fetch. Идём в backend напрямую.
  let requestUrl = url

  if (import.meta.server) {
    const runtimeConfig = useRuntimeConfig()
    const apiTarget = String(runtimeConfig.apiTarget || '').replace(/\/+$/, '')

    if (apiTarget) {
      requestUrl = `${apiTarget}${url.replace(/^\/api/, '')}`
    }
  }

  const $token =  useCookie('token')
  const token = $token.value

  const result = {
    success: true,
    data: undefined as any,
    error: undefined as any,
  }

  const headers: Record<string, string> = {
    ...(options.headers || {})
  }

  if (!!options?.removePreferHeader) {
    delete headers.Prefer
  }

  // FormData нельзя сериализовать в JSON: браузер сам выставит
  // multipart/form-data и boundary. Обычные объекты отправляем как JSON.
  const isFormData =
    typeof FormData !== 'undefined' && options.body instanceof FormData

  const body = isFormData || typeof options.body === 'string'
    ? options.body
    : options.body
      ? JSON.stringify(options.body)
      : options.body

  // Для FormData Content-Type выставляет браузер (нужен boundary).
  const hasContentType = !!Object.keys(headers).find(
    (name) => name.toLowerCase() === 'content-type'
  )

  if (body && !isFormData && !hasContentType) {
    headers['Content-Type'] = 'application/json'
  }

  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  return $fetch(requestUrl, {
    ...options,
    body,
    retry: 0, // https://github.com/nuxt/nuxt/issues/23457
    method: options?.method || 'GET',
    headers,
  })
    .then((data) => {
      let parsed = data
      try {
        parsed = JSON.parse(data)
      }
      catch (e) { }
      result.success = !parsed?.error
      result.error = parsed?.error
      result.data = (parsed?.data || parsed?.success)

      notifyResult(result)

      return result
    })
    .catch((error: any) => {
      let parsed = error.data
      console.error('[useRequest]', options?.method || 'GET', url, error?.message || error)
      try {
        parsed = JSON.parse(error.data)
      }
      catch (e) { }

      result.success = false
      const fallbackMessage = error?.response
        ? 'Попробуйте повторить попытку позже'
        : 'Сервер недоступен. Проверьте подключение и повторите попытку.'

      result.error = {
        code: parsed?.code || parsed?.error?.code || -100,
        title: parsed?.title || parsed?.error?.title || 'Ошибка',
        description: parsed?.description || parsed?.error?.description || fallbackMessage,
        message: parsed?.message || parsed?.error?.message || fallbackMessage,
        data: parsed?.error?.data,
        error: parsed?.error,
        response: parsed || error,
      }
      notifyResult(result)
      return result
    })
}
