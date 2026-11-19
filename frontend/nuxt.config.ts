// https://nuxt.com/docs/api/configuration/nuxt-config

// В Docker запросы /api/* уходят на backend-контейнер,
// локально — на uvicorn по умолчанию.
// Nitro отрезает совпавший префикс (/api/) перед пересылкой,
// поэтому в target должен остаться /api.
const apiProxyTarget = process.env.API_PROXY_TARGET || 'http://127.0.0.1:3001/api'
// Корень backend: оттуда отдаётся статика /uploads (результаты обработки ИИ).
const backendOrigin = apiProxyTarget.replace(/\/api\/?$/, '')
const isProduction = process.env.NODE_ENV === 'production'

export default defineNuxtConfig({
  compatibilityDate: '2025-05-15',
  devtools: { enabled: false },

    runtimeConfig: {
        // Только для SSR: прямой адрес backend API, чтобы $fetch с относительным
        // путём не уходил в Nitro-роутер (там /api/* нет).
        // На клиенте запросы идут по относительным путям через прокси.
        apiTarget: apiProxyTarget,
    },

    nitro: {
        prerender: {
            ignore: [
                '/api/',
            ],
        },
        // Production-сборка (nuxt build) тоже проксирует /api/* на backend.
        // В dev-режиме используется devProxy ниже.
        routeRules: isProduction
            ? {
                '/api/**': {
                    proxy: `${apiProxyTarget}/**`,
                },
                '/uploads/**': {
                    proxy: `${backendOrigin}/uploads/**`,
                },
            }
            : {},
        devProxy: {
            "/api/" : {
                target:  apiProxyTarget,
                changeOrigin: true,
            },
            "/uploads/" : {
                target:  `${backendOrigin}/uploads`,
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
