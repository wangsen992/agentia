# Agentia Architecture Diagrams

Diagrams rendered with [Mermaid Live Editor](https://mermaid.live) or GitHub Markdown.

***

## 1. System Architecture

```mermaid
graph TB
    Mod["Moderator"]
    subgraph Inbox["Shared /tmp/inbox"]
        A_IN["analyst.jsonl"]
        B_IN["critic.jsonl"]
        Resp["responses/"]
    end
    subgraph CA["Container A"]
        PA["Poller"]
    end
    subgraph CB["Container B"]
        PB["Poller"]
    end
    Mod --> A_IN
    Mod --> B_IN
    PA --> A_IN
    PB --> B_IN
    PA --> Resp
    PB --> Resp
```

***

## 2. send() — Request/Response Flow

```mermaid
sequenceDiagram
    participant M as Moderator
    participant IR as InboxRelay
    participant FS as /tmp/inbox
    participant P as Poller
    participant G as Gateway

    M->>IR: send("analyst", "What is 2+2?")
    IR->>FS: docker cp msg.jsonl to analyst.jsonl
    Note over IR: generates correlation_id, polls response file
    IR-->>P: message waiting in inbox
    loop every 2s
        P->>FS: read analyst.jsonl
    end
    FS-->>P: [{"id": "...", "content": "What is 2+2?"}]
    P->>G: openclaw agent --message "What is 2+2?"
    G-->>P: "2 + 2 = 4"
    P->>FS: write response to responses/<corr_id>.jsonl
    P->>FS: mark_processed(msg.id)
    IR-->>M: "2 + 2 = 4"
```

***

## 3. send_async() — Fire-and-Forget Flow

```mermaid
sequenceDiagram
    participant M as Moderator
    participant IR as InboxRelay
    participant FS as /tmp/inbox
    participant P as Poller

    M->>IR: send_async("critic", "do this task")
    IR->>FS: docker cp msg.jsonl to critic.jsonl
    IR-->>M: returns immediately (True)
    Note over P: [continues other work]
    loop every 2s
        P->>FS: read critic.jsonl
    end
    FS-->>P: [{"id": "...", "content": "do this task"}]
    P->>P: process message
    P->>FS: mark_processed(msg.id)
    Note over M,P: No response expected or waited for
```

***

## 4. Broadcast — One-to-Many

```mermaid
sequenceDiagram
    participant M as Moderator
    participant IR as InboxRelay
    participant FS as /tmp/inbox
    participant PA as Poller A
    participant PB as Poller B

    M->>IR: broadcast(["analyst", "critic"], "Topic: AI ethics")
    IR->>FS: docker cp msg.jsonl to analyst.jsonl
    IR->>FS: docker cp msg.jsonl to critic.jsonl
    IR-->>M: {"analyst": True, "critic": True}
    Par
        PA->>PA: poll, read, process
    and
        PB->>PB: poll, read, process
    End
```

***

## 5. Multi-Agent Conversation (Moderator Orchestration)

```mermaid
sequenceDiagram
    participant M as Moderator
    participant A as Analyst Agent
    participant C as Critic Agent

    M->>A: system: You are the Analyst
    M->>C: system: You are the Critic
    M->>A: intro: Topic Is AI helpful
    M->>C: intro: Topic Is AI helpful

    M->>A: build_prompt topic history=empty
    A-->>M: AI is helpful because
    M->>C: build_prompt topic history=Turn1
    C-->>M: However AI has drawbacks
    M->>A: build_prompt topic history=Turn1 Turn2
    A-->>M: Valid points but

Diagram 6: Poller Internal Flow

## 6. Poller Internal Flow

```mermaid
flowchart TD
    Start(["start poller --agent-id analyst"])
    Poll["poll_once()"]
    Read["inbox.read_all()"]
    Empty{msgs empty?}
    Process["for each msg: process_message()"]
    Corr{has correlation_id?}
    WriteResp["write response to responses/<corr_id>.jsonl"]
    Mark["inbox.mark_processed([ids])"]
    Sleep["sleep(poll_interval)"]
    Stop(["stop"])

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
    Sleep --> Poll
```
