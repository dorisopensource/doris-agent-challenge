# Tools do proxy

Base: `PROXY_URL` (padrão `http://proxy:3000`). Todas as tools são `POST` com corpo JSON e **sempre** recebem
`conversation_id`: o proxy descobre quem é o usuário a partir dele (a conversa é registrada quando o proxy repassa o
`/chat` ao agente). Campos extras no corpo são ignorados.

## Envelope

Sucesso:

```json
{ "ok": true, "data": { "...": "..." } }
```

Erro (sempre com um status HTTP diferente de 2xx):

```json
{ "ok": false, "error": { "code": "upstream_timeout", "message": "…", "retryable": true } }
```

`retryable` diz se tentar de novo pode funcionar.

| Código | HTTP | Quando |
|---|---|---|
| `conversation_not_found` | 404 | `conversation_id` desconhecido |
| `invalid_request` | 400 | corpo inválido (campo faltando, tipo errado) |
| `not_found` | 422 | id de produto, peça ou try-on que não existe para este usuário |
| `unsupported_combination` | 400 | try-on com mais de uma peça |
| outros (ex.: `upstream_timeout`) | 5xx | falhas do serviço; olhe o `retryable` |

Os tempos de resposta abaixo são os normais; o serviço pode ficar mais lento.

---

## `POST /tools/search_by_text`

Busca produtos no catálogo por texto (~0,5–1 s).

```json
{ "conversation_id": "c1", "query": "camisa de linho branca", "limit": 6 }
```

`limit`: padrão 6, máximo 12. A busca compara palavras do texto com nome, tags e descrição. **Ela não filtra por
preço, tamanho ou cor**: se a pessoa pediu "até R$300", quem filtra é o agente. Pode voltar vazia.

```json
{ "ok": true, "data": { "products": [
  { "search_item_id": "p01", "order": 0, "name": "Camisa de linho branca", "store": "Ateliê Maré",
    "price": 249.9, "currency_code": "BRL", "currency_symbol": "R$", "url": "https://loja.exemplo/p01",
    "image_url": "https://…/products/p01.jpg",
    "description": "Camisa de linho leve, manga longa, corte reto. Ótima para dias quentes." }
] } }
```

## `POST /tools/garment_creation`

Cria a peça (garment) a partir de um resultado da busca. É necessária antes do try-on (~3–5 s).

```json
{ "conversation_id": "c1", "search_item_id": "p01" }
```

```json
{ "ok": true, "data": { "garment_id": "0191a7e3-…", "ghost_image_url": "https://…/products/p01.jpg",
  "type": "TOP", "category": "shirt", "status": "PROCESSED", "metadata": {} } }
```

Criar a mesma peça de novo devolve o mesmo `garment_id`. Esta versão só aceita `search_item_id` (não cria peças a
partir de fotos enviadas pela pessoa).

## `POST /tools/tryon`

Veste **uma** peça no avatar da pessoa (~8–12 s). A peça pode vir do `garment_creation` ou do guarda-roupa.

```json
{ "conversation_id": "c1", "garment_ids": ["0191a7e3-…"], "avatar_pose": "NORMAL" }
```

```json
{ "ok": true, "data": { "tryon_id": "cd3aac42-…", "look_id": "5b59efc0-…", "garment_ids": ["0191a7e3-…"],
  "image_url": "https://…/tryons/u_ana/p01.jpg", "created_at": "2026-11-11T22:53:54+00:00",
  "status": "PROCESSED", "avatar_id": "avatar_u_ana", "avatar_pose": "NORMAL", "is_saved": false } }
```

Mais de uma peça → 400 `unsupported_combination`. `avatar_pose` só aceita `NORMAL`. O try-on **não aparece** para
a pessoa até o agente chamar `show_artifact`.

## `POST /tools/avatar`

```json
{ "ok": true, "data": { "avatars": [ { "avatar_id": "avatar_u_ana", "lifecycle_status": "READY",
  "poses": [ { "pose": "NORMAL", "status": "PROCESSED", "image_url": "https://…/avatars/u_ana.jpg" } ] } ] } }
```

## `POST /tools/looks`

Looks da pessoa, do mais recente para o mais antigo: primeiro os try-ons gerados, depois os looks antigos.

```json
{ "conversation_id": "c1", "limit": 20 }
```

```json
{ "ok": true, "data": { "looks": [
  { "look_id": "look_ana_1", "garment_ids": ["w_ana_1"], "description": "Calça jeans do dia a dia",
    "tryon_image_url": "https://…/tryons/u_ana/w_ana_1.jpg", "created_at": "2026-11-01T14:00:00Z" }
] } }
```

## `POST /tools/wardrobe`

Peças que a pessoa já tem. Filtro opcional por tipo (`TOP`, `BOTTOM`, `DRESS`…).

```json
{ "conversation_id": "c1", "garment_types": ["TOP"] }
```

```json
{ "ok": true, "data": { "garments": [
  { "garment_id": "w_ana_2", "type": "TOP", "category": "tshirt", "ghost_image_url": "https://…/garments/w_ana_2.jpg",
    "metadata": { "tags": ["camiseta", "branca"] } }
] } }
```

## `POST /tools/show_artifact`

Mostra um card no chat da pessoa, durante o turno em andamento.

```json
{ "conversation_id": "c1", "type": "TRYON_CARD", "value": "cd3aac42-…" }
```

| `type` | `value` | O que aparece |
|---|---|---|
| `PRODUCT` | `search_item_id` | Card com foto, nome, loja, preço e link |
| `GARMENT` | `garment_id` (criado ou do guarda-roupa) | Card com a imagem da peça |
| `TRYON_CARD` | `tryon_id` ou `look_id` (inclusive de looks antigos) | Imagem grande do try-on |

Resposta: `{ "ok": true }`.

---

## Depuração (não use no agente)

- `GET /admin/log?conversation_id=<id>`: turnos (mensagem, texto final, resultado, duração) e as chamadas de tools
  de cada turno, com pedido, status e resposta.
- `POST /admin/reset`: apaga conversas, logs e contadores de falhas. Os dados de teste não mudam.
- `GET /conversations?user_id=` e `GET /conversations/<id>/messages`: histórico usado pela barra lateral do frontend.

Imagens dos dados de teste também ficam em `http://localhost:3000/seed-images/…`, mas as URLs que as tools devolvem
são públicas, para que os modelos consigam abri-las.
