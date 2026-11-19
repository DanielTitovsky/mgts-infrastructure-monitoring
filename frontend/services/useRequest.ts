import config from '~/config'
import { mockRequest } from '~/services/mockApi'

type RequestBody = Record<string, unknown> | string | FormData

interface Options{
  method?: string,
  headers?: Record<string, string>,
  body?: RequestBody,
  removePreferHeader?: boolean
}

export function useRequest(url: string, options: Options = {}) {
  if (config.useMocks) {
    return mockRequest(url, options)
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
      result.error = {
        code: parsed?.code || parsed?.error?.code || -100,
        title: parsed?.title || parsed?.error?.title || 'Ошибка',
        description: parsed?.description || parsed?.error?.description || 'Попробуйте повторить попытку позже',
        message: parsed?.message || parsed?.error?.message || 'Попробуйте повторить попытку позже',
        data: parsed?.error?.data,
        error: parsed?.error,
        response: parsed || error,
      }
      return result
    })
}
