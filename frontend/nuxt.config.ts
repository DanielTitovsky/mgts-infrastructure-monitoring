import config from './config'
// https://nuxt.com/docs/api/configuration/nuxt-config
import Aura from '@primeuix/themes/aura'
import tailwindcss from '@tailwindcss/vite'

// В Docker запросы /api/* уходят на backend-контейнер,
// локально — на uvicorn по умолчанию.
// Nitro отрезает совпавший префикс (/api/) перед пересылкой,
// поэтому в target должен остаться /api.
const apiProxyTarget = process.env.API_PROXY_TARGET || config.apiUrl
// Корень backend: оттуда отдаётся статика /uploads (результаты обработки ИИ).
const backendOrigin = apiProxyTarget.replace(/\/api\/?$/, '')
const isProduction = process.env.NODE_ENV === 'production'

export default defineNuxtConfig({
  compatibilityDate: '2025-05-15',
  devtools: { enabled: false },

    // Всплывающие уведомления (izitoast) для успешных и ошибочных действий.
    modules: ['nuxt-toast', '@primevue/nuxt-module'],

    primevue: {
        // nuxt-toast owns useToast in this app; importing PrimeVue's composable
        // under the same auto-import name would silently change notifications.
        composables: {
            include: [],
        },
        options: {
            ripple: true,
            theme: {
                preset: Aura,
                options: {
                    darkModeSelector: '.app-dark',
                },
            },
        },
    },

    runtimeConfig: {
        // Только для SSR: прямой адрес backend API, чтобы $fetch с относительным
        // путём не уходил в Nitro-роутер (там /api/* нет).
        // На клиенте запросы идут по относительным путям через прокси.
        apiTarget: apiProxyTarget,
        public: {
            // Demo mode is opt-in and only routes useRequest through mockApi.
            demoMode: config.useMocks,
        },
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
        '@/assets/tailwind.css',
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
            {rel: 'icon', type: 'image/x-icon', href: '/favicon.ico'},
            {rel: 'stylesheet', href: 'https://fonts.cdnfonts.com/css/lato'},
        ]
    },

    vite: {
        plugins: [tailwindcss()],
    },
})
