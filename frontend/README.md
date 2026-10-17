# Frontend - Cloud Workflow Validator

This directory houses the frontend application for the Compiler-Based Cloud Workflow Validator.

## Ownership
- **Lead Developer**: Pavithra (React frontend, interactive workflow graphs, visualization)
- **Branch**: `feat/frontend`

## Planned Tech Stack
- **Framework**: React 18+ with TypeScript
- **Build Tool**: Vite
- **Styling**: Tailwind CSS / modern CSS
- **Visualization**: React Flow / Cytoscape.js / D3 for interactive dependency graph rendering
- **API Client**: Fetch / Axios / TanStack Query connecting to the FastAPI backend

## Planned Getting Started
When initializing the frontend project:
```bash
# Initialize Vite React + TypeScript template (if starting from scratch)
# cd frontend
npm install

# Copy environment configuration
cp .env.example .env

# Run development server (default: http://localhost:5173)
npm run dev

# Build production bundle (output: dist/)
npm run build
```

## Environment Configuration
See [frontend/.env.example](.env.example):
- `VITE_API_BASE_URL`: Base URL of the backend API (e.g., `http://localhost:8000` in dev, or the deployed Vercel backend URL in production).

## Deployment (Vercel)
The frontend is configured for independent static hosting on Vercel:
- **Framework Preset**: Vite
- **Root Directory**: `frontend`
- **Build Command**: `npm run build`
- **Output Directory**: `dist`
For detailed deployment instructions, refer to [docs/deployment.md](../docs/deployment.md).
