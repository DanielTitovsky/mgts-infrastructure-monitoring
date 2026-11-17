// https://nuxt.com/docs/api/configuration/nuxt-config

// В Docker запросы /api/* уходят на backend-контейнер,
// локально — на uvicorn по умолчанию.
// Nitro отрезает совпавший префикс (/api/) перед пересылкой,
// поэтому в target должен остаться /api.
const apiProxyTarget = process.env.API_PROXY_TARGET || 'http://127.0.0.1:3001/api'

export default defineNuxtConfig({
  compatibilityDate: '2025-05-15',
  devtools: { enabled: false },

    nitro: {
        prerender: {
            ignore: [
                '/api/',
            ],
        },
        devProxy: {
            "/api/" : {
                target:  apiProxyTarget,
                changeOrigin: true,
            }
        }
    },

    css: [
        '@/scss/_reset.scss',
        "@/public/fonts/inter.css",
        '@/scss/main.scss',
    ],

    head: {
        title: 'Мониторинг инфраструктуры МГТС',
        htmlAttrs: {
            lang: 'ru'
        },
        meta: [
            {charset: 'utf-8'},
            {name: 'viewport', content: 'width=device-width, initial-scale=1'},
            {hid: 'description', name: 'description', content: 'Система мониторинга городской инфраструктуры МГТС с применением компьютерного зрения'},
            {name: 'format-detection', content: 'telephone=no'}
        ],
        link: [
            {rel: 'icon', type: 'image/x-icon', href: '/favicon.ico'}
        ]
    },

    vite: {
        css: {
            preprocessorOptions: {
                scss: {
                    additionalData: '@use "@/scss/_variables.scss" as *;',
                },
            },
        }
    },
})
