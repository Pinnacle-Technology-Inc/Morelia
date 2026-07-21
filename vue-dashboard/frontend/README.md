# Guarded Experiment Dashboard — Vue

Standalone Vue 3 migration of the Guarded Experiment Dashboard.

## Architecture

- Vue 3 Composition API and single-file components
- Vite build tooling
- Manual CSS in `src/styles.css`
- Pinnacle-inspired design tokens in `src/design-system/`
- Vue-native Lucide icons
- No React, Tailwind, MUI, Radix, Emotion, or CSS-in-JS runtime

## Commands

```bash
npm install
npm run dev
npm test
npm run build
```

The legacy React implementation remains in the parent folder as a temporary visual and behavior reference. After the Vue application is accepted, the parent project can be replaced or archived in a separate cleanup step.
