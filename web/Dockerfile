FROM node:24.15.0-alpine

WORKDIR /app

ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}

COPY package.json ./
RUN npm install

COPY . .

RUN npm run build

EXPOSE 3000

ENV HOSTNAME=0.0.0.0

CMD ["npm", "run", "start"]
