FROM node:20-alpine AS builder
WORKDIR /app
# Copy lockfile alongside package.json so npm ci can produce a reproducible install.
# npm ci is faster than npm install and fails if package-lock.json is out of sync.
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# analysisContext.ts imports this from the repo root. The frontend build
# context is only ./frontend, so the file is supplied as an extra context.
COPY --from=ptm_shared study_display.json /ptm_shared/study_display.json
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
