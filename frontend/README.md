# Synapse Frontend

Next.js 15 portal + marketing site for the Synapse multi-tenant AI healthcare platform.

## Stack

- Next.js 15 (App Router) + TypeScript
- Tailwind CSS v4 + shadcn/ui
- TanStack Query, React Hook Form, Zod
- Axios (JWT interceptors + refresh)
- Framer Motion (minimal)
- Lucide icons

## Setup

```bash
# Node 20+
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

App: [http://localhost:3000](http://localhost:3000)  
API (Django): [http://127.0.0.1:8000/api/v1/docs](http://127.0.0.1:8000/api/v1/docs)

## Demo login

After `python manage.py seed_demo` on the backend:

- Clinic slug: `acme-cardiology`
- Email: `admin@acme-cardiology.example`
- Password: `admin123`

## Architecture

```
src/
  app/               # Marketing, auth, dashboard routes
  components/        # UI + marketing + dashboard chrome
  features/chat/     # Chatbot widget + message components
  hooks/             # React Query hooks
  services/          # API service functions
  lib/api/           # Axios clients + token helpers
  providers/         # Auth + Query providers
  types/             # API + chat types
```

## Backend gaps (intentional TODOs)

These pages are UI-ready with `TODO: Backend endpoint required`:

- Register / forgot / reset / verify email
- Clinic settings, specialties, insurance, business hours
- Analytics, billing checkout
- Contact form delivery

Existing APIs are used for login, refresh, me, doctors, services, patients, appointments, documents, and staff chatbot QA.
