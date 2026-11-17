FROM node:22-alpine

ENV NUXT_TELEMETRY_DISABLED=1

WORKDIR /app

# Копируем всё сразу: postinstall-хук `nuxt prepare` требует исходники.
COPY . .

# npm install (а не ci), чтобы подтянулись platform-specific optional-зависимости
# под linux/musl, которых нет в lock-файле, собранном на Windows.
RUN npm install --no-audit --no-fund

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]
