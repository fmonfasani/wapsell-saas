# RAG Training - Custom Prompt Examples

## ¿Cómo usar?

### Opción 1: Prompt directo
```bash
python scripts/train_rag.py \
  --tenant-id {id} \
  --prompt "Genera 100 queries de familias con niños buscando departamentos"
```

### Opción 2: Prompt desde archivo
```bash
python scripts/train_rag.py \
  --tenant-id {id} \
  --prompt-file scripts/my-custom-prompt.txt
```

---

## Ejemplos de Prompts Custom

### 1. Compradores de Familias
```
Genera 100 queries de familias con niños que buscan departamentos.
Las preguntas deben enfocarse en:
- Escuelas cercanas
- Espacios verdes / parques
- Seguridad del barrio
- Departamentos grandes (3+ dormitorios)
- Distancia a colegios

Las queries deben ser como las haría una madre/padre buscando
hogar para su familia. Variadas, naturales y humanas.

Formato: Una query por línea, sin números, solo las queries.
```

### 2. Compradores de Inversión Inmobiliaria
```
Genera 100 queries de inversores inmobiliarios profesionales.
Las preguntas deben enfocarse en:
- Rentabilidad (ROI, rendimiento)
- Apreciación de propiedad
- Zonas de crecimiento
- Demanda de alquiler
- Impuestos y gastos
- Potencial de reventa

Las queries deben sonar como las haría un inversor profesional.
Técnicas, específicas, sobre números y rentabilidad.

Formato: Una query por línea, sin números, solo las queries.
```

### 3. Compradores de Lujo
```
Genera 100 queries de compradores de propiedades de lujo.
Las preguntas deben enfocarse en:
- Amenities premium (piscina, gym, SPA)
- Vistas panorámicas
- Pisos altos
- Materiales de calidad
- Ubicaciones exclusivas
- Casas de estilo (moderno, clásico, minimalista)
- Cocheras/estacionamiento

Estilo de comprador: sofisticado, exigente, con presupuesto alto.

Formato: Una query por línea, sin números, solo las queries.
```

### 4. Compradores Jóvenes (Primera Vivienda)
```
Genera 100 queries de jóvenes profesionales buscando su primera vivienda.
Las preguntas deben enfocarse en:
- Presupuesto limitado (buscan bajo cierto monto)
- Proximidad a trabajo/transporte
- Barrios trendy
- Departamentos pequeños (1-2 dormitorios)
- Amenities sociales (coworking, cafeterías)
- Seguridad

Estilo: casual, directo, sin mucha experiencia en real estate.

Formato: Una query por línea, sin números, solo las queries.
```

### 5. Entrenamiento Bilingüe (ES + EN)
```
Genera 50 queries en español y 50 en inglés. Buyers internacionales
y locales buscando departamentos en Buenos Aires.

Las queries en inglés deben ser como las haría un extranjero:
- Preguntas sobre barrios específicos
- Amenities internacionales (Netflix, WiFi, etc)
- Facilidades para mudanza

Las queries en español para compradores locales tradicionales.

Ambos grupos variados en edad, presupuesto, necesidades.

Formato: Una query por línea, sin números, solo las queries.
```

### 6. Búsquedas Específicas por Barrio
```
Genera 100 queries enfocadas SOLO en propiedades de Palermo.

Las preguntas deben ser sobre:
- Características específicas de Palermo
- Micro-barrios dentro de Palermo (Soho, Hollywood, Viejo)
- Comercios y vida nocturna
- Restaurantes y cafeterías
- Vida estudiantil/joven
- Transporte en Palermo

Objetivo: entrenar al agent específicamente en Palermo.

Formato: Una query por línea, sin números, solo las queries.
```

### 7. Comprador Experimentado
```
Genera 100 queries de compradores expertos que ya compraron propiedades.
Las preguntas deben ser:
- Técnicas y específicas
- Sobre documentación/papelería
- Negociación de precio
- Comparación entre propiedades
- Análisis detallado de gastos
- Condiciones de compra

Estilo: profesional, sabe qué busca, hace preguntas inteligentes.

Formato: Una query por línea, sin números, solo las queries.
```

---

## ¿Cómo se ejecuta?

```
1. Escribís tu custom prompt (o usas uno de los ejemplos)
2. Ejecutas: python scripts/train_rag.py --tenant-id {id} --prompt-file prompts/familias.txt
3. Sistema:
   - Analiza el catálogo
   - Usa TU prompt para generar 100 queries
   - Agent procesa cada una
   - RAG se entrena específicamente para tu público
4. Resultado: Agent optimizado para tu tipo de buyer
```

---

## Tips para mejores resultados

✓ Sé específico: "jóvenes de 25-35 años" vs "jóvenes"
✓ Incluye contexto: "que buscan primera casa" vs solo "compradores"
✓ Menciona valores: "bajo $150k" vs "baratos"
✓ Sé natural: "¿Hay algo con piscina?" vs "propiedades con amenities"
✓ Variedad: cubre diferentes escenarios y preguntas
