import { $fetch } from 'ofetch'
import config from '~/config'
import { mockRequest } from '~/services/mockApi'

interface Options{
  method?: string,
  headers?: {},
  body?: {} | string,
  removePreferHeader?: boolean
}

export function useRequest(url: string, options: Options = {}) {
  if (config.useMocks) {
    return mockRequest(url, options)
  }

  const $token =  useCookie('token')
  const token = $token.value

  const result = {
    success: true,
    data: undefined,
    error: undefined,
  }

  const headers: Record<string, string> = {
    ...(options.headers || {})
  }

  if (!!options?.removePreferHeader) {
    delete headers.Prefer
  }

  if (typeof options.body !== "string") {
    options.body = JSON.stringify(options.body)
  }

  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  return $fetch(url, {
    ...options,
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
      console.log(error.data)
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
