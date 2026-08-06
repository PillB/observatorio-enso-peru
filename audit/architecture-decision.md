# Decisión de arquitectura (ADR)

## Decisión: Retener el frontend estático (Opción A)

El frontend estático en `public/index.html` es la arquitectura canónica de producción.
El repositorio contiene también una aplicación Next.js, pero ésta NO se despliega
en GitHub Pages y no debe considerarse producción.

## Justificación
- GitHub Pages requiere contenido estático.
- El frontend estático ya funciona en producción.
- Migrar a Next.js static export requeriría `output: 'export'` y eliminar
  las API routes (chatbot), perdiendo funcionalidad.
- El frontend estático tiene menor superficie de ataque y menor latencia.

## Acciones
- Documentar que `public/index.html` es el único frontend de producción.
- El código Next.js en `src/` se retiene como referencia pero no se despliega.
- El pipeline de datos debe publicar artefactos en `public/data/`.
