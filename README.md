# Desafio: agente da Doris

## Contexto

A Doris é uma assistente de moda. A pessoa conversa com ela no app, e a Doris busca peças, recomenda
looks, gera um **try-on** (a peça vestida no avatar da pessoa) e opina sobre o que ela está usando.

Neste repositório você já recebe tudo **menos o agente**:

- **Frontend** de chat (em `http://localhost:3000`).
- **Proxy**: o serviço que fica entre o app e o agente. Ele repassa cada mensagem ao agente (com o perfil básico da
  pessoa), devolve a resposta em streaming para o frontend e expõe as **tools** (busca, criação de peça, try-on,
  guarda-roupa, looks…).
- **Dados de teste**: 3 usuários (Ana, Bruno e Carla), cada um com avatar, guarda-roupa e looks anteriores, e um
  catálogo de produtos fictícios.

```
frontend ──▶ proxy /chat ──▶ seu agente (agent/)
                ▲                  │
                └──── /tools/* ◀───┘          seu agente ──▶ OpenRouter
```

## Sua tarefa

Construir o agente em `agent/`.

- **O escopo é maior que 4 horas, de propósito.** Não esperamos tudo pronto: queremos ver o que você escolhe fazer
  primeiro e com que qualidade. Priorizar faz parte da avaliação.
- **As 4 horas começam no `git clone`.** Não há cronômetro; confiamos em você. Anote início e fim no seu README.
- **Pode (e deve) usar IA**, com bom senso. Você precisa saber explicar tudo o que entregar.
- Recomendamos **LangGraph**, mas não é obrigatório. Qualquer linguagem serve, desde que rode no Docker e siga o
  contrato abaixo.

## O que esperamos do agente

O fluxo principal: a pessoa pede algo → o agente **busca** → **escolhe** bons itens → **cria a peça**
(`garment_creation`) → gera o **try-on** → **mostra** o resultado para a pessoa.

Cenários:

| # | Usuário | Mensagem |
|---|---|---|
| 1 | Ana | "Me acha uma camisa de linho branca até R$300" |
| 2 | Bruno | "Tenho um casamento na praia sábado, o que eu visto?" |
| 3 | Carla | "O que você acha do meu último look?" |
| 4 | Ana | Conversa A: "Odeio amarelo, visto M e curto estilo minimalista." Depois, em uma conversa nova: "Me sugere algo pra um jantar" |
| 5 | Ana | "Tem jaqueta jeans?" e depois "Quero provar a jaqueta de couro preta" |
| 6 | Bruno | "Oi" e "Qual a capital da França?" |

Na avaliação usamos variações destes cenários.

## Como rodar

```bash
cp .env.example .env              # coloque a chave da OpenRouter em OPENROUTER_API_KEY
docker compose up --build         # proxy + agente
# abra http://localhost:3000
```

- Para depurar: `GET http://localhost:3000/admin/log?conversation_id=<id>` mostra os turnos e as chamadas de tools
  registradas pelo proxy.
- Os testes do proxy rodam com `pip install -r requirements-dev.txt && pytest`.

## Contrato do agente

O proxy chama o seu agente em `AGENT_URL` (padrão `http://agent:8000`). O agente chama as tools em `PROXY_URL`
(padrão `http://proxy:3000`).

O contrato é **compatível com OpenAI Chat Completions em streaming**. Só três pontos são da Doris, e estão marcados
abaixo como extensões.

### `POST /v1/chat/completions`

```json
{
  "model": "doris-agent",
  "stream": true,
  "user": "u_bruno",
  "messages": [
    { "role": "user", "content": [
      { "type": "text", "text": "Tenho um casamento na praia sábado, o que eu visto?" },
      { "type": "image_url", "image_url": { "url": "data:image/jpeg;base64,…" } }
    ] }
  ],
  "metadata": {
    "conversation_id": "5f0c…",
    "profile": { "name": "Bruno", "gender": "MALE", "city": "Rio de Janeiro" }
  }
}
```

- `user`: id da pessoa. Pode vir com sufixo (`u_ana__abc`); trate cada `user` como uma pessoa diferente.
- `messages`: **extensão — só a mensagem atual.** Diferente do uso comum da API, o proxy não envia o histórico:
  guardar a conversa e decidir o que vai para cada chamada de modelo é responsabilidade do agente. As partes
  `image_url` são as imagens que a pessoa anexou (data URI).
- `metadata`: **extensão.** `conversation_id` (use nas chamadas de tools) e `profile`, o perfil básico da pessoa
  (nome, gênero, cidade), sem gostos nem preferências.

A resposta é `text/event-stream` no formato padrão da OpenAI:

```
data: {"object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"Para a praia, "},"finish_reason":null}]}
data: {"object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"linho é ótimo."},"finish_reason":null}]}
data: {"object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}
data: [DONE]
```

- **Extensão — feedback de tools:** um chunk com `choices: []` e o campo `doris`:

  ```
  data: {"object":"chat.completion.chunk","choices":[],"doris":{"type":"feedback","id":"tryon-1","text":"Gerando seu try-on…","state":"running"}}
  ```

  O frontend mostra uma linha por `id`; um novo chunk com o mesmo `id` atualiza a linha. `state`: `running`
  (spinner), `done` (✓) ou `error` (✗). Clientes OpenAI comuns ignoram esse campo.
- Erro: `data: {"error":{"message":"…","type":"agent_error"}}` encerra o turno com erro.
- O turno termina no `data: [DONE]` (ou no chunk com `finish_reason`, se o `[DONE]` não vier).

Para **mostrar** produtos, peças e try-ons para a pessoa, o agente chama `POST /tools/show_artifact`. O proxy
coloca o card no chat. Um try-on que nunca é mostrado não aparece para a pessoa.

O turno é **encerrado pelo proxy em 100 segundos**.

### `GET /health`

Responde 200 quando o agente está pronto.

As tools estão documentadas em [`docs/proxy-api.md`](docs/proxy-api.md).

## Modelos disponíveis

A chave que enviamos dá acesso a estes modelos na [OpenRouter](https://openrouter.ai):

- [`openai/gpt-6-luna`](https://openrouter.ai/openai/gpt-6-luna)
- [`google/gemini-3.8-flash`](https://openrouter.ai/google/gemini-3.8-flash)
- [`google/gemma-4-26b-a4b-it`](https://openrouter.ai/google/gemma-4-26b-a4b-it)
- [`qwen/qwen3.5-9b`](https://openrouter.ai/qwen/qwen3.5-9b)
- [`~typesafe/jev-latest`](https://openrouter.ai/~typesafe/jev-latest)
- [`openai/text-embedding-3-small`](https://openrouter.ai/openai/text-embedding-3-small)

## Regras

- Altere apenas `agent/` e o `docker-compose.yml`: você pode mudar o serviço `agent` (volumes, variáveis,
  `depends_on`) e adicionar serviços (banco, cache, tracing…).
- Não altere `proxy/`, `seed-images/` nem os dados de teste: na avaliação usamos a
  nossa cópia deles.
- O agente não pode chamar `/admin/*` nem `/conversations/*`. Esses endpoints existem só para depuração, para a nossa
  avaliação e para o histórico do frontend.
- A única chamada externa permitida é para a OpenRouter, com a chave fornecida. Todo o resto roda dentro do compose.
- Nunca faça commit da chave.

## Chave da OpenRouter

A chave da OpenRouter foi enviada no e-mail em que você recebeu este desafio. Coloque-a no `.env`
(`OPENROUTER_API_KEY=`) e nunca faça commit dela. A chave tem um limite de gasto e é revogada depois do prazo.

Se você não recebeu a chave, ou se o link do e-mail disser que ela já foi visualizada, nos avise antes de continuar.

## Entrega

1. Clique em **Use this template** e crie um repositório **público** na sua conta.
2. Trabalhe na branch **`solucao`**.
3. Abra um **pull request** de `solucao` para o `main` do seu repositório.
4. Envie o link do PR para nós.

O arquivo `agent/README.md` é seu. Ele precisa ter: ideia e arquitetura; decisões e trade-offs; o que ficou de fora
e por quê; próximos passos; como você usou IA (onde ajudou e onde errou); horário de início e de fim; como rodar.
