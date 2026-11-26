# Evidencia Bloque C — Amazon S3

- Fecha: `2026-11-09T00:50:02-06:00`
- Navegador: ChatGPT in-app browser, sesión aislada
- Automatización: Playwright semántico mediante Codex
- Dominio verificado: `https://calculator.aws/`
- Servicio: Amazon Simple Storage Service (S3)
- Región: `us-east-1` — US East (N. Virginia)
- S3 Standard: `100 GB per month`
- GET/SELECT y otras solicitudes: `100000` mensuales
- Transferencia de salida: Internet, `10 GB per month`
- Costo mensual observado: `3.24 USD`
- Total de 12 meses observado: `38.88 USD`
- URL compartida: <https://calculator.aws/#/estimate?id=bad2a0531379cb5d5aec0c4b36c820b57532c8bd>

La exportación JSON fue generada por AWS Pricing Calculator. Su SHA-256 es
`f583d2348512d253d67baad7a628de8cf213454c9e66d49c29e8e47ef2c96fa0`.
El archivo `pricing-calculator-evidence.json` enlaza esos resultados con la
revisión y el SHA-256 de la arquitectura utilizada.

La automatización localiza elementos por su semántica accesible. El validador
`S3ExportEvidenceBuilder` falla si cambian las etiquetas, propiedades, región,
moneda o estructura de la exportación; no utiliza coordenadas fijas ni precios
locales.

## Análisis económico del Bloque D

`finops-economic-analysis.json` registra `3.24 USD/mes` y `38.88 USD/año` como
subtotal S3 verificado. El presupuesto aprobado del handoff es `75.00 USD/mes`,
pero la comparación es provisional: falta estimar AWS KMS. La cobertura es 50 %
de recursos y 60 % de dimensiones, por lo que el resultado presupuestario es
`not_evaluable` y no existe una decisión de aprobación.
