# ProcureMind Frontend

Next.js 15 App Router frontend application with TypeScript, Tailwind CSS, and TanStack Query.

## Setup & Running with pnpm

1. Install dependencies:
```bash
pnpm install
```

2. Configure environment:
```bash
cp .env.example .env.local
```

3. Run development server:
```bash
pnpm dev
```

The frontend will be available at [http://localhost:3000](http://localhost:3000).
It connects to the FastAPI backend at `http://localhost:8000` by default.

4. Build for production:
```bash
pnpm build
```

