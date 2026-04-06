# Agentia Architecture Diagrams

Diagrams rendered with [Mermaid Live Editor](https://mermaid.live) or GitHub Markdown.

---

## 1. System Architecture

```mermaid
graph TB
    subgraph Host["Host Machine"]
        Mod["Moderator<br/>(InboxRelay)"]
        subgraph Inbox["Shared Inbox Directory<br/>/tmp/inbox"]
            A_IN["analyst.jsonl"]
            B_IN["critic.jsonl"]
            Resp["responses/"]
        end
    end

    subgraph ContainerA["Container A: analyst"]
        GA["Gateway"]
        PA["Poller<br/>(--agent-id analyst)"]
    end

    subgraph ContainerB["Container B: critic"]
        GB["Gateway"]
        PB["Poller<br/>(--agent-id critic)"]
    end

    Mod -->|"docker cp| I1"| A_IN
    Mod -->|"docker cp| I2"| B_IN
    Mod -->|"poll| Resp"| Mod
    PA -->|"read| A_IN
    PB -->|"read| B_IN
    PA -->|"write| Resp"
    PB -->|"write| Resp"

    style Mod fill:#2563eb,color:#fff
    style Inbox fill:#f3f4f6
    style Resp fill:#fef3c7
```

---

## 2. send() — Request/Response Flow

```mermaid
sequenceDiagram
    participant M as Moderator
    participant IR as InboxRelay
    participant FS as /tmp/inbox
    participant P as Poller (Container A)
    participant G as Gateway

    M->>IR: send("analyst", "What is 2+2?")
    IR->>FS: docker cp msg.jsonl → analyst.jsonl
    Note over IR: generates correlation_id<br/>polls response file
    IR-->>P: [message waiting in inbox]
    P->>P: poll (every 2s)
    P->>FS: read analyst.jsonl
    FS-->>P: [{"id": "...", "content": "What is 2+2?"}]
    P->>G: openclaw agent --message "What is 2+2?"
    G-->>P: "2 + 2 = 4"
    P->>FS: write response to<br/>responses/<correlation_id>.jsonl
    P->>FS: mark_processed(msg.id)
    IR-->>M: "2 + 2 = 4"
```

---

## 3. send_async() — Fire-and-Forget Flow

```mermaid
sequenceDiagram
    participant M as Moderator
    participant IR as InboxRelay
    participant FS as /tmp/inbox
    participant P as Poller (Container B)

    M->>IR: send_async("critic", "do this task")
    IR->>FS: docker cp msg.jsonl → critic.jsonl
    IR-->>M: returns immediately (True)
    Note over P: [continues other work]
    P->>P: poll (every 2s)
    P->>FS: read critic.jsonl
    FS-->>P: [{"id": "...", "content": "do this task"}]
    P->>P: process message
    P->>FS: mark_processed(msg.id)
    Note over M,P: No response expected or waited for
```

---

## 4. Broadcast — One-to-Many

```mermaid
sequenceDiagram
    participant M as Moderator
    participant IR as InboxRelay
    participant FS as /tmp/inbox
    participant PA as Poller A
    participant PB as Poller B

    M->>IR: broadcast(["analyst", "critic"], "Topic: AI ethics")
    IR->>FS: docker cp msg.jsonl → analyst.jsonl
    IR->>FS: docker cp msg.jsonl → critic.jsonl
    IR-->>M: {"analyst": True, "critic": True}
    Par
        PA->>PA: poll → read → process
    and
        PB->>PB: poll → read → process
    End
```

---

## 5. Multi-Agent Conversation (Moderator Orchestration)

```mermaid
sequenceDiagram
    participant M as Moderator
    participant A as Analyst Agent
    participant C as Critic Agent

    M->>A: system: "You are the Analyst"
    M->>C: system: "You are the Critic"
    M->>A: intro: "Topic: Is AI helpful"
    M->>C: intro: "Topic: Is AI helpful"

    rect rgb(240, 248, 255)
        Note over M,A,C: Turn 1 — Analyst speaks
        M->>A: build_prompt(topic, history=[])
        A-->>M: "AI is helpful because..."
        M->>M: record TurnRecord(1, analyst, response)
    end

    rect rgb(255, 248, 240)
        Note over M,A,C: Turn 2 — Critic responds
        M->>C: build_prompt(topic, history=[Turn 1])
        C-->>M: "However, AI has drawbacks..."
        M->>M: record TurnRecord(2, critic, response)
    end

    rect rgb(240, 255, 248)
        Note over M,A,C: Turn 3 — Analyst rebuts
        M->>A: build_prompt(topic, history=[T1, T2])
        A-->>M: "The critic raises valid points, but..."
    end
```

---

## 6. Poller Internal Flow

```mermaid
graph TD
    Start["start poller<br/>--agent-id analyst"]
    Poll["poll_once()"]
    Read["inbox.read_all()"]
    Empty{msgs empty?}
    Process["for each msg:<br/>process_message()"]
    Corr{has<br/>correlation_id?}
    WriteResp["write response to<br/>responses/<corr_id>.jsonl"]
    Mark["inbox.mark_processed([ids])"]
    Sleep["sleep(poll_interval)"]
    Stop["stop"]

    Start --> Poll
    Poll --> Read
    Read --> Empty
    Empty -->|yes| Sleep
    Empty -->|no| Process
    Process --> Corr
    Corr -->|yes| WriteResp
    Corr -->|no| Mark
    WriteResp --> Mark
    Mark --> Sleep
    Sleep -->|loop| Poll
    Sleep -->|Ctrl+C| Stop

    style Start fill:#2563eb,color:#fff
    style Poll fill:#16a34a,color:#fff
    style Stop fill:#dc2626,color:#fff
```
